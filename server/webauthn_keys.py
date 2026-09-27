import base64
import os

from flask import session
from webauthn import (generate_authentication_options,
                      generate_registration_options, options_to_json,
                      verify_authentication_response,
                      verify_registration_response)

from webauthn.helpers import base64url_to_bytes
from webauthn.helpers.exceptions import (InvalidAuthenticationResponse,
                                         InvalidRegistrationResponse)
from webauthn.helpers.structs import (AuthenticatorSelectionCriteria,
                                      PublicKeyCredentialDescriptor,
                                      ResidentKeyRequirement,
                                      UserVerificationRequirement)

from .models import (WebAuthnCredential, _utcnow, credential_by_raw_id,
                     credentials_for, db, load_user)

REG_CHALLENGE = "webauthn_reg"
AUTH_CHALLENGE = "webauthn_auth"


class KeyError_(Exception):
    """Anything the user should see as a polite failure, not a 500."""

def rp_id():
    return (os.environ.get("WEBAUTHN_RP_ID") or "localhost").strip()

def rp_name():
    return (os.environ.get("WEBAUTHN_RP_NAME") or "Piko").strip()

def origin():
    return (os.environ.get("WEBAUTHN_ORIGIN") or "http://localhost:5000").strip()


def configured():
    return bool(os.environ.get("WEBAUTHN_RP_ID")
                and os.environ.get("WEBAUTHN_ORIGIN"))


def _stash(key, challenge):
    session[key] = base64.b64encode(challenge).decode()


def _take(key):
    raw = session.pop(key, None)
    if not raw:
        raise KeyError_("That took too long. Start again.")
    return base64.b64decode(raw)

def begin_registration(user, require_user_verification=True):
    existing = credentials_for(user)
    options = generate_registration_options(
        rp_id=rp_id(),
        rp_name=rp_name(),
        # Opaque handle, not the email: it is stored on the authenticator and
        # may be shown by the OS, and it must never need to change.
        user_id=str(user.id).encode("utf-8"),
        user_name=user.email or user.username or str(user.id),
        user_display_name=user.name or user.username or "Piko user",
        # Stops the same key being enrolled twice on one account.
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=c.credential_id) for c in existing],
        authenticator_selection=AuthenticatorSelectionCriteria(
            # PREFERRED, not REQUIRED: a resident key enables passwordless
            # sign-in, but older keys have very little slot storage and
            # REQUIRED makes them fail outright.
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=(UserVerificationRequirement.REQUIRED
                               if require_user_verification
                               else UserVerificationRequirement.PREFERRED),
        ),
    )
    _stash(REG_CHALLENGE, options.challenge)
    return options_to_json(options)

def finish_registration(user, body, name="Security key", admin_capable=False):
    challenge = _take(REG_CHALLENGE)
    try:
        result = verify_registration_response(
            credential=body,
            expected_challenge=challenge,
            expected_origin=origin(),
            expected_rp_id=rp_id(),
            require_user_verification=False,   # checked per-ceremony below
        )
    except InvalidRegistrationResponse as exc:
        raise KeyError_("That key could not be registered: %s" % exc)

    if credential_by_raw_id(result.credential_id) is not None:
        raise KeyError_("That key is already registered.")

    cred = WebAuthnCredential(
        user_id=user.id,
        credential_id=result.credential_id,
        public_key=result.credential_public_key,
        sign_count=result.sign_count or 0,
        aaguid=str(result.aaguid or "")[:64],
        transports=",".join(body.get("transports") or [])[:120],
        name=(name or "Security key").strip()[:80] or "Security key",
        admin_capable=bool(admin_capable),
    )
    db.session.add(cred)
    db.session.commit()
    return cred

def begin_authentication(user=None, admin_only=False):
    allow = []
    if user is not None:
        creds = credentials_for(user)
        if admin_only:
            creds = [c for c in creds if c.admin_capable]
        if not creds:
            raise KeyError_("No security key is registered for this account.")
        allow = [PublicKeyCredentialDescriptor(id=c.credential_id) for c in creds]

    options = generate_authentication_options(
        rp_id=rp_id(),
        allow_credentials=allow,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    _stash(AUTH_CHALLENGE, options.challenge)
    return options_to_json(options)


def finish_authentication(body, user=None, admin_only=False,
                          require_user_verification=True):
    challenge = _take(AUTH_CHALLENGE)
    raw_id = base64url_to_bytes(body.get("rawId") or body.get("id") or "")
    cred = credential_by_raw_id(raw_id)
    if cred is None:
        raise KeyError_("That key is not registered here.")
    if user is not None and cred.user_id != user.id:
        raise KeyError_("That key belongs to a different account.")
    if admin_only and not cred.admin_capable:
        raise KeyError_("That key is not enrolled for admin access.")

    try:
        result = verify_authentication_response(
            credential=body,
            expected_challenge=challenge,
            expected_origin=origin(),
            expected_rp_id=rp_id(),
            credential_public_key=cred.public_key,
            credential_current_sign_count=cred.sign_count,
            require_user_verification=require_user_verification,
        )
    except InvalidAuthenticationResponse as exc:
        raise KeyError_("That key did not verify: %s" % exc)


    if result.new_sign_count == 0 and cred.sign_count == 0:
        pass
    elif result.new_sign_count <= cred.sign_count:
        raise KeyError_("That key looks cloned. It has been refused.")

    cred.sign_count = result.new_sign_count
    cred.last_used_at = _utcnow()
    db.session.commit()

    owner = user or load_user(cred.user_id)
    if owner is None:
        raise KeyError_("That key's account no longer exists.")
    return owner, cred
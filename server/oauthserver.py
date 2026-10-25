import base64
import hashlib
import secrets
from collections import namedtuple
from datetime import timedelta
from urllib.parse import urlencode, urlsplit

from flask import (Blueprint, jsonify, make_response, redirect,
                   render_template, request)

from . import csrf
from .apikeys import mint, resolve
from .apikeys import revoke as revoke_key
from .models import (API_SCOPES, ApiKey, OAuthClient, OAuthCode, OAuthDevice,
                     OAuthRefresh, _utcnow, db)
from .publicapi import _client_ip, _rate_limited
from .session import current_user, login_required

oauth_bp = Blueprint("oauth", __name__)

DEVICE_TTL = timedelta(minutes=10)
DEVICE_INTERVAL = 5
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
CODE_TTL = timedelta(minutes=2)
ACCESS_TTL = timedelta(hours=1)
REFRESH_TTL = timedelta(days=60)
WRITE_SCOPES = {"submissions:write"}
TOKEN_PER_MINUTE = 30
MAX_APPS_PER_OWNER = 5

CODE_ALPHABET = "BCDFGHJKMNPQRSTVWXZ23456789"   

Ctx = namedtuple("Ctx", "client uri state scopes challenge")

def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _b64(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def pkce_ok(verifier, challenge):
    if not (43 <= len(verifier or "") <= 128):
        return False
    try:
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
    except UnicodeEncodeError:
        return False
    return secrets.compare_digest(_b64(digest), challenge or "")

def _loopback(parts):
    return parts.scheme == "http" and parts.hostname in ("127.0.0.1", "::1")

def redirect_allowed(client, uri):
    want = urlsplit(uri or "")
    if not want.scheme or want.fragment:
        return False
    for registered in client.redirect_uris or []:
        have = urlsplit(registered)
        if _loopback(have) and _loopback(want):
            if (have.hostname, have.path) == (want.hostname, want.path):
                return True
        elif registered == uri:
            return True
    return False


def parse_scopes(client, text):
    asked = list(dict.fromkeys((text or "").split()))
    if not asked:
        raise ValueError("No scope was requested.")
    for scope in asked:
        if scope not in API_SCOPES:
            raise ValueError("Unknown scope %r." % scope)
        if scope not in (client.max_scopes or []):
            raise ValueError("This app is not allowed %r." % scope)
        if scope in WRITE_SCOPES and not client.trusted:
            raise ValueError("%r is only available to verified apps." % scope)
    return asked

def _user_code():
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    return raw[:4] + "-" + raw[4:]

def _error_page(message, status=400):
    resp = make_response(render_template("oauth_error.html", message=message),
                         status)
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _bounce(uri, state, **params):
    if state:
        params["state"] = state
    params["iss"] = request.url_root.rstrip("/")
    sep = "&" if urlsplit(uri).query else "?"
    return redirect(uri + sep + urlencode(params))


def _find_client(cid):
    return db.session.execute(
        db.select(OAuthClient).filter_by(client_id=cid or "")
    ).scalar_one_or_none()

def _validate(values):
    client = _find_client(values.get("client_id"))
    if client is None or not client.is_live:
        return None, _error_page("That application is not known to Piko.")
    uri = values.get("redirect_uri", "")
    if not redirect_allowed(client, uri):
        return None, _error_page(
            "That return address is not registered for this application.")

    state = values.get("state", "")
    if values.get("response_type") != "code":
        return None, _bounce(uri, state, error="unsupported_response_type")

    challenge = values.get("code_challenge", "")
    if values.get("code_challenge_method") != "S256" or len(challenge) < 43:
        return None, _bounce(uri, state, error="invalid_request",
                             error_description="PKCE with S256 is required.")
    try:
        scopes = parse_scopes(client, values.get("scope"))
    except ValueError as exc:
        return None, _bounce(uri, state, error="invalid_scope",
                             error_description=str(exc))
    return Ctx(client, uri, state, scopes, challenge), None

@oauth_bp.route("/oauth/authorize")
@login_required
def authorize():
    ctx, early = _validate(request.args)
    if early is not None:
        return early
    resp = make_response(render_template("oauth_consent.html", client=ctx.client, scopes=ctx.scopes,
        labels=API_SCOPES, params=request.args))
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
    return resp

@oauth_bp.route("/oauth/authorize", methods=["POST"])
@login_required
def authorize_post():
    ctx, early = _validate(request.form)
    if early is not None:
        return early
    if request.form.get("answer") != "yes":
        return _bounce(ctx.uri, ctx.state, error="access_denied")

    raw = secrets.token_urlsafe(32)
    db.session.add(OAuthCode(
        code_hash=_sha(raw), client_id=ctx.client.id,
        user_id=current_user().id, redirect_uri=ctx.uri,
        scopes=ctx.scopes, code_challenge=ctx.challenge,
        expires_at=_utcnow() + CODE_TTL))
    db.session.commit()
    return _bounce(ctx.uri, ctx.state, code=raw)

def _oauth_error(code, description="", status=400):
    body = {"error": code}
    if description:
        body["error_description"] = description
    resp = jsonify(body)
    resp.status_code = status
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Pragma"] = "no-cache"
    return resp

def _authenticate_client():
    cid = request.form.get("client_id")
    secret = request.form.get("client_secret")
    basic = request.authorization
    if basic is not None and basic.type == "basic":
        cid, secret = basic.username, basic.password

    client = _find_client(cid)
    if client is None or not client.is_live:
        return None
    if client.confidential:
        if not secret or not secrets.compare_digest(
                client.secret_hash, _sha(secret)):
            return None
    return client

def _issue(client, user, scopes, family=None):
    try:
        api_key, access = mint(user, name=client.name, scopes=scopes,
                               expires_in=ACCESS_TTL, oauth_client=client)
    except ValueError as exc:
        # mint refuses admin scopes for anyone not on the allowlist. Without
        # this the token endpoint answers 500 instead of saying why.
        return _oauth_error("invalid_scope", str(exc))
    refresh = secrets.token_urlsafe(48)
    db.session.add(OAuthRefresh(
        token_hash=_sha(refresh), family=family or secrets.token_hex(8),
        client_id=client.id, user_id=user.id, api_key_id=api_key.id,
        scopes=list(scopes), expires_at=_utcnow() + REFRESH_TTL))
    db.session.commit()

    resp = jsonify(access_token=access, token_type="Bearer",
                   expires_in=int(ACCESS_TTL.total_seconds()),
                   refresh_token=refresh, scope=" ".join(scopes))
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Pragma"] = "no-cache"
    return resp


def _revoke_family(family):
    rows = db.session.execute(
        db.select(OAuthRefresh).filter_by(family=family)).scalars().all()
    now = _utcnow()
    for row in rows:
        row.revoked_at = row.revoked_at or now
        key = db.session.get(ApiKey, row.api_key_id) if row.api_key_id else None
        if key is not None and key.revoked_at is None:
            key.revoked_at = now
    db.session.commit()


def _by_hash(model, raw):
    return db.session.execute(
        db.select(model).filter_by(**{
            "code_hash" if model is OAuthCode else "token_hash": _sha(raw)})
    ).scalar_one_or_none()


def _grant_code(client):
    row = _by_hash(OAuthCode, request.form.get("code", ""))
    if row is None or row.client_id != client.id:
        return _oauth_error("invalid_grant", "Unknown authorization code.")
    if row.used_at is not None or row.expires_at <= _utcnow():
        return _oauth_error("invalid_grant", "That code has expired.")
    if request.form.get("redirect_uri") != row.redirect_uri:
        return _oauth_error("invalid_grant", "redirect_uri does not match.")
    if not pkce_ok(request.form.get("code_verifier"), row.code_challenge):
        return _oauth_error("invalid_grant", "The code verifier is wrong.")

    claimed = db.session.execute(
        db.update(OAuthCode)
        .where(OAuthCode.id == row.id, OAuthCode.used_at.is_(None))
        .values(used_at=_utcnow())).rowcount
    db.session.commit()
    if claimed != 1:
        return _oauth_error("invalid_grant", "That code was already used.")
    return _issue(client, row.user, row.scopes)


def _grant_refresh(client):
    row = _by_hash(OAuthRefresh, request.form.get("refresh_token", ""))
    if row is None or row.client_id != client.id:
        return _oauth_error("invalid_grant", "Unknown refresh token.")
    if row.used_at is not None:
        _revoke_family(row.family)
        return _oauth_error("invalid_grant",
                            "Refresh token reuse detected; sign in again.")
    if row.revoked_at is not None or row.expires_at <= _utcnow():
        return _oauth_error("invalid_grant", "That refresh token has expired.")

    
    narrower = (request.form.get("scope") or "").split()
    if narrower and not set(narrower) <= set(row.scopes):
        return _oauth_error("invalid_scope", "Scope can only be narrowed.")
    scopes = narrower or list(row.scopes)

    claimed = db.session.execute(
        db.update(OAuthRefresh)
        .where(OAuthRefresh.id == row.id, OAuthRefresh.used_at.is_(None))
        .values(used_at=_utcnow())).rowcount
    db.session.commit()
    if claimed != 1:
        _revoke_family(row.family)
        return _oauth_error("invalid_grant", "Refresh token reuse detected.")

    old = db.session.get(ApiKey, row.api_key_id) if row.api_key_id else None
    if old is not None:
        revoke_key(old)
    return _issue(client, row.user, scopes, family=row.family)


@oauth_bp.route("/oauth/token", methods=["POST"])
@csrf.exempt
def token():
    if _rate_limited("oauth:" + _client_ip(), TOKEN_PER_MINUTE):
        return _oauth_error("slow_down", "Too many requests.", 429)
    

    client = _authenticate_client()
    if client is None:
        return _oauth_error("invalid_client", status=401)

    grant = request.form.get("grant_type")
    if grant == "authorization_code":
        return _grant_code(client)
    if grant == DEVICE_GRANT:
            return _grant_device(client)
    if grant == "refresh_token":
        return _grant_refresh(client)
    return _oauth_error("unsupported_grant_type")
    

@oauth_bp.route("/oauth/revoke", methods=["POST"])
@csrf.exempt
def revoke():
    """RFC 7009. Always answers 200, so it cannot be used to probe tokens."""
    client = _authenticate_client()
    if client is None:
        return _oauth_error("invalid_client", status=401)

    raw = request.form.get("token", "")
    row = _by_hash(OAuthRefresh, raw)
    if row is not None and row.client_id == client.id:
        _revoke_family(row.family)
        return "", 200

    key = resolve(raw)
    if key is not None and key.oauth_client_id == client.id:
        linked = db.session.execute(
            db.select(OAuthRefresh).filter_by(api_key_id=key.id)
        ).scalar_one_or_none()
        if linked is not None:
            _revoke_family(linked.family)
        else:
            revoke_key(key)
    return "", 200


@oauth_bp.route("/.well-known/oauth-authorization-server")
def metadata():
    base = request.url_root.rstrip("/")
    resp = jsonify(
        issuer=base,
        authorization_endpoint=base + "/oauth/authorize",
        device_authorization_endpoint=base + "/oauth/device_authorization",
        token_endpoint=base + "/oauth/token",
        revocation_endpoint=base + "/oauth/revoke",
        response_types_supported=["code"],
        grant_types_supported=["authorization_code", "refresh_token", DEVICE_GRANT],
        code_challenge_methods_supported=["S256"],
        token_endpoint_auth_methods_supported=[
            "none", "client_secret_basic", "client_secret_post"],
        scopes_supported=sorted(API_SCOPES))
        
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


def connected_apps(user):
    """Apps this person has a live refresh token with, newest first."""
    return db.session.execute(
        db.select(OAuthClient)
        .join(OAuthRefresh, OAuthRefresh.client_id == OAuthClient.id)
        .where(OAuthRefresh.user_id == user.id,
               OAuthRefresh.revoked_at.is_(None),
               OAuthRefresh.expires_at > _utcnow())
        .group_by(OAuthClient.id)
        .order_by(db.func.max(OAuthRefresh.created_at).desc())
    ).scalars().all()


def disconnect(user, client):
    families = db.session.execute(
        db.select(OAuthRefresh.family).distinct()
        .where(OAuthRefresh.user_id == user.id,
               OAuthRefresh.client_id == client.id)).scalars().all()
    for family in families:
        _revoke_family(family)


def register_cli(app):
    @app.cli.command("oauth-seed")
    def _seed():
        wanted = sorted(API_SCOPES)
        client = _find_client("piko-cli")

        if client is None:
            db.session.add(OAuthClient(
                client_id="piko-cli", name="Piko CLI",
                description="The official command-line tool.",
                redirect_uris=["https://piko.aryan.my/callback"],
                max_scopes=wanted, first_party=True))
            db.session.commit()
            print("created piko-cli with %d scopes" % len(wanted))
            return

        have = list(client.max_scopes or [])
        added = [s for s in wanted if s not in have]
        dropped = [s for s in have if s not in wanted]
        if not added and not dropped:
            print("piko-cli already current (%d scopes)" % len(wanted))
            return

        client.max_scopes = wanted
        db.session.commit()
        print("updated piko-cli  +%s  -%s"
              % (", ".join(added) or "none", ", ".join(dropped) or "none"))

    @app.cli.command("oauth-prune")
    def _prune():
        cutoff = _utcnow() - timedelta(days=1)
        a = db.session.execute(db.delete(OAuthCode).where(
            OAuthCode.expires_at < cutoff)).rowcount
        b = db.session.execute(db.delete(OAuthRefresh).where(
            OAuthRefresh.expires_at < cutoff)).rowcount
        c = db.session.execute(db.delete(ApiKey).where(
            ApiKey.oauth_client_id.isnot(None),
            ApiKey.expires_at < cutoff)).rowcount
        
        db.session.commit()
        print("pruned %d codes, %d refresh tokens, %d access keys" % (a, b, c))


@oauth_bp.route("/oauth/device_authorization", methods=["POST"])
@csrf.exempt
def device_authorization():
    if _rate_limited("device:" + _client_ip(), TOKEN_PER_MINUTE):
        return _oauth_error("slow_down", "Too many requests.", 429)

    client = _find_client(request.form.get("client_id"))
    if client is None or not client.is_live:
        return _oauth_error("invalid_client", status=401)

    try:
        scopes = parse_scopes(client, request.form.get("scope", ""))
    except ValueError as exc:
        return _oauth_error("invalid_scope", str(exc))

    raw = secrets.token_urlsafe(32)
    for _ in range(5):
        code = _user_code()
        if db.session.execute(db.select(OAuthDevice.id)
                              .filter_by(user_code=code)).scalar() is None:
            break
    else:
        return _oauth_error("server_error", "Could not allocate a code.", 500)

    db.session.add(OAuthDevice(
        client_id=client.id, device_hash=_sha(raw), user_code=code,
        scopes=scopes, expires_at=_utcnow() + DEVICE_TTL))
    db.session.commit()

    base = request.url_root.rstrip("/")
    resp = jsonify(device_code=raw, user_code=code,
                   verification_uri=base + "/oauth/device",
                   verification_uri_complete="%s/oauth/device?code=%s"
                                             % (base, code),
                   expires_in=int(DEVICE_TTL.total_seconds()),
                   interval=DEVICE_INTERVAL)
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _device_by_code(code):
    return db.session.execute(
        db.select(OAuthDevice).filter_by(
            user_code=(code or "").strip().upper())).scalar_one_or_none()


@oauth_bp.route("/oauth/device", methods=["GET", "POST"])
@login_required
def device_verify():
    code = (request.form.get("user_code") if request.method == "POST"
            else request.args.get("code")) or ""

    row = _device_by_code(code) if code else None
    error = None
    if code and row is None:
        error = "That code is not one of yours"
    elif row is not None and not row.is_live:
        error = "That code has expired. Start again in your terminal."
        row = None

    if request.method == "POST" and row is not None:
        if request.form.get("answer") == "yes":
            row.user_id = current_user().id
            row.approved_at = _utcnow()
        else:
            row.denied_at = _utcnow()
        db.session.commit()
        return render_template("oauth_device.html", done=True,
                               approved=row.approved_at is not None,
                               client=row.client)

    resp = make_response(render_template(
        "oauth_device.html", done=False, row=row, code=code, error=error,
        labels=API_SCOPES, client=row.client if row else None,
        scopes=row.scopes if row else []))
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Frame-Options"] = "DENY"
    return resp

def _grant_device(client):
    row = _by_device(request.form.get("device_code", ""))
    if row is None or row.client_id != client.id:
        return _oauth_error("invalid_grant", "Unknown device code.")

    now = _utcnow()
    if row.consumed_at is not None:
        return _oauth_error("invalid_grant", "That code was already used.")
    if row.expires_at <= now:
        return _oauth_error("expired_token", "The code expired.")
    if row.denied_at is not None:
        return _oauth_error("access_denied", "The request was declined.")

    if (row.last_poll_at is not None
            and (now - row.last_poll_at).total_seconds() < DEVICE_INTERVAL - 1):
        row.last_poll_at = now
        db.session.commit()
        return _oauth_error("slow_down", "Poll no faster than %ds."
                            % DEVICE_INTERVAL, 400)

    row.last_poll_at = now
    if row.approved_at is None:
        db.session.commit()
        return _oauth_error("authorization_pending", "Nobody has approved it yet" )
    row.consumed_at = now
    scopes = list(row.scopes)
    user = row.user
    db.session.commit()
    return _issue(client, user, scopes)

def _by_device(raw):
    if not raw:
        return None
    return db.session.execute(
        db.select(OAuthDevice).filter_by(device_hash=_sha(raw))
    ).scalar_one_or_none()


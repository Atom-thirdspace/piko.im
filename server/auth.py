import os
import secrets

from flask import (
    Blueprint, abort, current_app, flash, make_response, redirect, render_template,
    request, session, url_for
)
from .devices import notify_new_device, remember_device
from .oauth import oauth, enabled_providers, OIDC_PROVIDERS, PROVIDERS
from .profile import fetch_profile
from .models import upsert_user, mark_welcome_sent, link_identity
from .mailer import send_welcome_email
from .session import current_user, is_safe_next, login_required

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/login/")
def login_page():
    if current_user():
        return redirect(url_for("dashboard.index"))
    return render_template(
        "login.html",
        providers=enabled_providers(),
        next=request.args.get("next", url_for("dashboard.index")),
    )

def _authorize_redirect(provider):
    session["oauth_nonce"] = secrets.token_urlsafe(16)

    client = oauth.create_client(provider)
    redirect_uri = url_for("auth.callback", provider=provider, _external=True)
    kwargs = {}
    if provider in OIDC_PROVIDERS:
        kwargs["nonce"] = session["oauth_nonce"]
    return client.authorize_redirect(redirect_uri, **kwargs)

@auth_bp.route("/login/<provider>/")
def login(provider):
    if current_user():
        return redirect(url_for("dashboard.index"))
    if provider not in current_app.config.get("ENABLED_PROVIDERS", []):
        abort(404)
    session.pop("oauth_link_user_id", None)      # a plain login is never a link
    session["oauth_next"] = request.args.get("next", url_for("dashboard.index"))
    return _authorize_redirect(provider)

@auth_bp.route("/connect/<provider>/", methods=["POST"])
@login_required
def connect(provider):
    """Start linking another provider to the signed-in account."""
    if provider not in current_app.config.get("ENABLED_PROVIDERS", []):
        abort(404)
    session["oauth_link_user_id"] = current_user().id
    return _authorize_redirect(provider)

_LINK_MESSAGES = {
    "linked": ("%s connected.", "success"),
    "already_linked": ("That %s account is already connected.", "success"),
    "taken": ("That %s account belongs to a different Piko user.", "error"),
    "provider_in_use": ("You already have a %s account connected. "
                        "Disconnect it first to use a different one.", "error"),
}

def _finish_link(provider, link_user_id, profile):
    user = current_user()
    # The link was started by a specific user; don't attach it to anyone else.
    if user is None or user.id != link_user_id:
        flash("Your session changed while connecting. Please try again.", "error")
        return redirect(url_for("auth.login_page"))

    message, category = _LINK_MESSAGES[link_identity(user, profile)]
    flash(message % PROVIDERS[provider]["label"], category)
    return redirect(url_for("profile.settings"))

@auth_bp.route("/auth/callback/<provider>/")
def callback(provider):
    if provider not in current_app.config.get("ENABLED_PROVIDERS", []):
        abort(404)

    # Pop unconditionally so a stale flag can't turn a later login into a link.
    link_user_id = session.pop("oauth_link_user_id", None)
    client = oauth.create_client(provider)
    try:
        token = client.authorize_access_token()
        if provider in OIDC_PROVIDERS:
            token["userinfo"] = client.parse_id_token(token, nonce=session.pop("oauth_nonce", None))

        profile = fetch_profile(provider, client, token)
    except Exception:
        current_app.logger.exception("OAuth callback error for %s", provider)
        flash("Authentication failed. Please try again.", "error")
        if link_user_id is not None:
            return redirect(url_for("profile.settings"))
        return redirect(url_for("auth.login_page"))

    if link_user_id is not None:
        # Linking doesn't need an email - the account already has one.
        return _finish_link(provider, link_user_id, profile)

    if not profile.get("email"):
        flash("Your account has no verified email we can use.", "error")
        return redirect(url_for("auth.login_page"))

    user, is_new = upsert_user(profile)

    if is_new:
        if send_welcome_email(user.email, user.name):
            mark_welcome_sent(user.id)
        else:
            current_app.logger.warning("welcome email failed for user %s", user.id)

    # Read `next` before clear() wipes it, then rotate the session on login.
    nxt = session.get("oauth_next", url_for("dashboard.index"))
    session.clear()
    session["user_id"] = user.id
    session.permanent = True

    if user.needs_onboarding:
        target = url_for("accounts.onboarding", next=nxt)
    elif user.needs_questionnaire:
        target = url_for("onboarding.page")
    else:
        target = nxt if is_safe_next(nxt) else url_for("dashboard.index")

    response = make_response(redirect(target))
    if is_new:
        remember_device(response, user)     # brand new account, nothing to warn about
    else:
        notify_new_device(user, response)
    return response

@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect("/")


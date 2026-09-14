import os
import secrets
from urllib.parse import urlparse, urljoin

from flask import (
    Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
)
from .oauth import oauth, PROVIDERS
from .profile import fetch_profile
from .models import upsert_user, mark_welcome_sent
from .mailer import send_welcome_email

auth_bp = Blueprint("auth", __name__)

def _is_safe_next(target):
    if not target:
        return False
    ref = urlparse(request.host_url)
    test = urlparse(urljoin(request.host_url, target))
    return test.scheme in ("http", "https") and ref.netloc == test.netloc

@auth_bp.route("/login/")
def login_page():
    enabled = current_app.config.get("ENABLED_PROVIDERS", [])
    from flask import render_template
    return render_template(
        "login.html",
        providers=[(n, PROVIDERS[n]["label"]) for n in enabled],
    )

@auth_bp.route("/login/<provider>/")
def login(provider):
    if provider not in current_app.config.get("ENABLED_PROVIDERS", []):
        abort(404)
    session["oauth_next"] = request.args.get("next", "/")
    session["oauth_nonce"] = secrets.token_urlsafe(16)

    client = oauth.create_client(provider)
    redirect_uri = url_for("auth.callback", provider=provider, _external=True)
    kwargs = {}
    if provider == "google":  # OIDC only
        kwargs["nonce"] = session["oauth_nonce"]
    return client.authorize_redirect(redirect_uri, **kwargs)

@auth_bp.route("/auth/callback/<provider>/")
def callback(provider):
    if provider not in current_app.config.get("ENABLED_PROVIDERS", []):
        abort(404)
    client = oauth.create_client(provider)
    try:
        token = client.authorize_access_token()
        if provider == "google":
            token["userinfo"] = client.parse_id_token(token, nonce=session.pop("oauth_nonce", None))
        profile = fetch_profile(provider, client, token)
    except Exception:
        current_app.logger.exception("OAuth callback error for %s", provider)
        flash("Authentication failed. Please try again.", "error")
        return redirect(url_for("auth.login_page"))

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
    nxt = session.get("oauth_next", "/")
    session.clear()
    session["user_id"] = user.id
    session.permanent = True

    return redirect(nxt if _is_safe_next(nxt) else "/")

@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect("/")


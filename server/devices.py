from datetime import datetime, timezone

from flask import current_app, request, url_for
from itsdangerous import BadSignature, URLSafeTimedSerializer

from .mailer import send_login_alert_email

DEVICE_COOKIE = "piko_device"
DEVICE_MAX_AGE = 60 * 60 * 24 * 365
DEVICE_SALT = "piko-known-device"


def _serializer():
    return URLSafeTimedSerializer(current_app.secret_key, salt=DEVICE_SALT)


def known_device(user):
    raw = request.cookies.get(DEVICE_COOKIE)
    if not raw:
        return False
    try:
        data = _serializer().loads(raw, max_age=DEVICE_MAX_AGE)
    except BadSignature:
        return False
    return data.get("uid") == user.id


def remember_device(response, user):
    response.set_cookie(
        DEVICE_COOKIE, _serializer().dumps({"uid": user.id}),
        max_age=DEVICE_MAX_AGE, httponly=True, samesite="Lax",
        secure=current_app.config.get("SESSION_COOKIE_SECURE", False),
    )
    return response


def _client_ip():
    # Only trust the header when a proxy you control sets it (needs ProxyFix).
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def notify_new_device(user, response):
    """Email on the first sign-in from a browser, then mark it known."""
    if not known_device(user):
        sent = send_login_alert_email(
            user.email, user.name,
            when=datetime.now(timezone.utc),
            ip=_client_ip(),
            user_agent=request.headers.get("User-Agent", "unknown"),
            settings_url=url_for("profile.settings", _external=True),
        )
        if not sent:
            current_app.logger.warning("login alert failed for user %s", user.id)
    return remember_device(response, user)

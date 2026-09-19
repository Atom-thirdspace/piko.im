from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

VERIFY_SALT = "piko-email-verify"
VERIFY_MAX_AGE = 60 * 60 * 24          # a day


def _serializer():
    return URLSafeTimedSerializer(current_app.secret_key, salt=VERIFY_SALT)


def make_verify_token(user):
    # Binding the address means the link dies if the email later changes.
    return _serializer().dumps({"uid": user.id, "email": user.email})


def read_verify_token(token, max_age=VERIFY_MAX_AGE):
    """Returns (payload, None) or (None, "expired" | "invalid")."""
    try:
        return _serializer().loads(token, max_age=max_age), None
    except SignatureExpired:
        return None, "expired"
    except BadSignature:
        return None, "invalid"

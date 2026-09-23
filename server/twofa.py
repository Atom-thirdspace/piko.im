import base64
import os
import secrets
import time

from cryptography.fernet import Fernet, InvalidToken as FernetInvalid
from cryptography.hazmat.primitives.hashes import SHA1
from cryptography.hazmat.primitives.twofactor import InvalidToken
from cryptography.hazmat.primitives.twofactor.totp import TOTP
from flask import session
from werkzeug.security import check_password_hash, generate_password_hash

from .models import _utcnow, db, load_user

STEP = 30                 # RFC 6238's default; Google Authenticator ignores any other
DIGITS = 6
DRIFT = 1
ISSUER = "Piko"
BACKUP_COUNT = 10

PENDING = "2fa_pending"
CHALLENGE_TTL = 300
MAX_TRIES = 5

def _fernet():
    key = (os.environ.get("TOTP_ENC_KEY") or "").strip()
    return Fernet(key.encode()) if key else None

def configured():
    """No key, no 2FA. Storing these secrets in the clear isn't a fallback."""
    return _fernet() is not None

def new_secret():
    return secrets.token_bytes(20)

def manual_key(secret):
    raw = base64.b32encode(secret).decode().rstrip("=")
    return " ".join(raw[i:i + 4] for i in range(0, len(raw), 4))

def seal(secret):
    return _fernet().encrypt(secret).decode()

def unseal(stored):
    box = _fernet()
    if box is None or not stored:
        return None
    try:
        return box.decrypt(stored.encode())
    except (FernetInvalid, TypeError, ValueError):
        return None

def provisioning_uri(secret, email):
    return TOTP(secret, DIGITS, SHA1(), STEP).get_provisioning_uri(email, ISSUER)

def qr_svg(uri):
    try:
        import qrcode
        import qrcode.image.svg
    except ImportError:
        return None
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, border=2)
    return img.to_string(encoding="unicode")    

def check_code(secret, code, last_step=None):
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit() or len(code) != DIGITS:
        return None

    totp = TOTP(secret, DIGITS, SHA1(), STEP)
    now = int(time.time())
    for offset in range(-DRIFT, DRIFT + 1):
        at = now + offset * STEP
        step = at // STEP
        if last_step is not None and step <= last_step:
            continue
        try:
            totp.verify(code.encode(), at)
        except InvalidToken:
            continue
        return step
    return None


def make_backup_codes(count=BACKUP_COUNT):
    plain = ["%s-%s" % (secrets.token_hex(2), secrets.token_hex(2))
             for _ in range(count)]
    return plain, [generate_password_hash(code) for code in plain]

def spend_backup_code(user, candidate):
    candidate = (candidate or "").strip().lower().replace(" ", "")
    if not candidate:
        return False
    remaining = list(user.backup_codes or [])
    for hashed in remaining:
        if check_password_hash(hashed, candidate):
            remaining.remove(hashed)
            user.backup_codes = remaining      # reassign - ARRAY edits in place don't stick
            db.session.commit()
            return True
    return False


def enabled(user):
    return user is not None and bool(user.totp_secret and user.totp_confirmed_at)

def enable(user, secret, hashed_codes, step):
    user.totp_secret = seal(secret)
    user.totp_confirmed_at = _utcnow()
    user.totp_last_step = step
    user.backup_codes = hashed_codes
    db.session.commit()


def disable(user):
    user.totp_secret = None
    user.totp_confirmed_at = None
    user.totp_last_step = None
    user.backup_codes = []
    db.session.commit()


def begin_challenge(user, nxt):
    session.clear()
    session[PENDING] = {"uid": user.id, "at": time.time(), "next": nxt, "tries": 0}


def pending():
    data = session.get(PENDING)
    if not isinstance(data, dict):
        return None, None
    if time.time() - (data.get("at") or 0) > CHALLENGE_TTL:
        session.pop(PENDING, None)
        return None, None
    user = load_user(data.get("uid"))
    if user is None or not enabled(user):
        session.pop(PENDING, None)
        return None, None
    return user, data

def count_try():
    data = session.get(PENDING) or {}
    data["tries"] = (data.get("tries") or 0) + 1
    session[PENDING] = data
    if data["tries"] >= MAX_TRIES:
        session.pop(PENDING, None)
        return True
    return False


def end_challenge():
    session.pop(PENDING, None)
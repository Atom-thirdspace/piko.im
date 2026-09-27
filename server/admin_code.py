import secrets
from datetime import timedelta

from werkzeug.security import check_password_hash, generate_password_hash

from .mailer import _send
from .models import AdminLoginCode, _utcnow, db

TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5
RESEND_AFTER = timedelta(seconds=60)

def _live(user):
    return db.session.execute(
        db.select(AdminLoginCode)
        .where(AdminLoginCode.user_id == user.id,
               AdminLoginCode.used_at.is_(None),
               AdminLoginCode.expires_at > _utcnow())
        .order_by(AdminLoginCode.created_at.desc()).limit(1)
    ).scalar_one_or_none()


def send_code(user):
    live = _live(user)
    if live is not None and _utcnow() - live.created_at < RESEND_AFTER:
        return False, "A code was just sent. Check your inbox."

    # Any older code stops working the moment a new one is issued.
    db.session.execute(
        db.update(AdminLoginCode)
        .where(AdminLoginCode.user_id == user.id,
               AdminLoginCode.used_at.is_(None))
        .values(used_at=_utcnow()))
    
    code = "%06d" % secrets.randbelow(1_000_000)
    db.session.add(AdminLoginCode(
        user_id=user.id, code_hash=generate_password_hash(code),
        expires_at=_utcnow() + TTL))
    db.session.commit()

    ok = _send(
        user.email,
        "Your Piko admin code",
        "<p>Your admin code is <strong style='font-size:22px;letter-spacing:3px'>"
        "%s</strong></p><p>It expires in 10 minutes and can be used once. "
        "If you did not ask for it, someone knows your password - change it.</p>"
        % code)
    if not ok:
        return False, "Could not send the email. Try your security key."
    return True, "Code sent to your admin address."

def verify_code(user, candidate):
    candidate = (candidate or "").strip()
    row = _live(user)
    if row is None or not candidate:
        return False

    if row.attempts >= MAX_ATTEMPTS:
        row.used_at = _utcnow()          # burn it rather than allow grinding
        db.session.commit()
        return False

    row.attempts += 1
    if not check_password_hash(row.code_hash, candidate):
        db.session.commit()
        return False

    row.used_at = _utcnow()
    db.session.commit()
    return True
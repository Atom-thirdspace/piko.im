import hmac
import os
import time
from datetime import timedelta
from functools import wraps

from flask import abort, current_app, redirect, request, session, url_for
from werkzeug.security import check_password_hash
from .models import AdminAction, _utcnow, db
from .session import current_user

SESSION_KEY = "admin_unlock"
FAIL_ACTION = "admin.unlock_failed"
OPEN_ACTION = "admin.unlock"

MAX_FAILURES = 5
LOCKOUT = timedelta(minutes=15)
DEFAULT_TTL_MINUTES = 120

_warned_no_passcode = False

def admin_emails():
    return {e.strip().lower()
            for e in (os.environ.get("ADMIN_EMAILS") or "").split(",") if e.strip()}

def is_admin(user):
    return user is not None and (user.email or "").lower() in admin_emails()

def _hashed():
    return (os.environ.get("ADMIN_PASSCODE_HASH") or "").strip()


def _plain():
    return os.environ.get("ADMIN_PASSCODE") or ""


def passcode_set():
    return bool(_hashed() or _plain())

def verify_passcode(candidate):
    candidate = (candidate or "").strip()
    if not candidate:
        return False
    stored = _hashed()
    if stored:
        return check_password_hash(stored, candidate)
    plain = _plain()
    return bool(plain) and hmac.compare_digest(plain, candidate)

def _ttl_seconds():
    try:
        minutes = int(os.environ.get("ADMIN_UNLOCK_MINUTES", DEFAULT_TTL_MINUTES))
    except (TypeError, ValueError):
        minutes = DEFAULT_TTL_MINUTES
    return max(60, minutes * 60)

def session_unlocked(user):
    data = session.get(SESSION_KEY) or {}
    # Bound to the user id, so switching accounts in the same browser re-locks.
    if not isinstance(data, dict) or data.get("uid") != user.id:
        return False
    opened = data.get("at")
    if not isinstance(opened, (int, float)):
        return False
    return (time.time() - opened) < _ttl_seconds()

def unlock_session(user):
    session[SESSION_KEY] = {"uid": user.id, "at": time.time()}
    _record(user, OPEN_ACTION, detail=request.remote_addr or "")

def lock_session():
    session.pop(SESSION_KEY, None)

def _record(user, action, detail=""):
    db.session.add(AdminAction(admin_id=user.id, action=action,
                               target=(user.email or "")[:120], detail=detail[:500]))
    db.session.commit()


def record_failure(user):
    _record(user, FAIL_ACTION, detail=request.remote_addr or "")

def _window_start(user):
    """Failures only count since the last successful unlock."""
    cutoff = _utcnow() - LOCKOUT
    last_ok = db.session.execute(
    db.select(AdminAction.created_at)
        .where(AdminAction.admin_id == user.id, AdminAction.action == OPEN_ACTION)
        .order_by(AdminAction.created_at.desc()).limit(1)
    ).scalar_one_or_none()
    return max(cutoff, last_ok) if last_ok else cutoff

def recent_failures(user):
    return db.session.execute(
        db.select(db.func.count()).select_from(AdminAction).where(
            AdminAction.admin_id == user.id,
            AdminAction.action == FAIL_ACTION,
            AdminAction.created_at >= _window_start(user),
        )
    ).scalar() or 0

def lockout_minutes_left(user):
    if recent_failures(user) < MAX_FAILURES:
        return 0
    newest = db.session.execute(
        db.select(AdminAction.created_at)
        .where(AdminAction.admin_id == user.id, AdminAction.action == FAIL_ACTION)
        .order_by(AdminAction.created_at.desc()).limit(1)
    ).scalar_one_or_none()
    if newest is None:
        return 0
    left = (newest + LOCKOUT) - _utcnow()
    return max(0, -(-int(left.total_seconds()) // 60))

def admin_email_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            return redirect(url_for("auth.login_page", next=request.full_path))
        if not is_admin(user):
            abort(404)
        return view(*args, **kwargs)
    return wrapped

def admin_required(view):
    @wraps(view)
    @admin_email_required
    def wrapped(*args, **kwargs):
        global _warned_no_passcode
        if not passcode_set():
            # Fail closed where it matters. A gate that quietly disables itself
            # because a deploy forgot the variable is not a gate.
            if os.environ.get("FLASK_ENV") == "production":
                current_app.logger.error(
                    "ADMIN_PASSCODE / ADMIN_PASSCODE_HASH is unset - /admin is closed")
                abort(503)
            if not _warned_no_passcode:
                current_app.logger.warning(
                    "No admin passcode set - the /admin gate is open (dev only)")
                _warned_no_passcode = True
            return view(*args, **kwargs)

        if not session_unlocked(current_user()):
            return redirect(url_for("admin.unlock", next=request.full_path))
        return view(*args, **kwargs)
    return wrapped

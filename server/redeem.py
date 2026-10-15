import re
import secrets
from datetime import timedelta

import threading
import time as _time

from sqlalchemy.exc import IntegrityError

from . import economy, notify
from .models import RedeemCode, RedeemUse, Subscription, User, _utcnow, db
from .progress import award_xp

CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{2,31}$")
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

COINS, XP, PRO, FREEZE, COSMETIC = "coins", "xp", "pro", "freeze", "cosmetic"

REWARDS = {
    COINS: "Coins",
    XP: "XP",
    PRO: "Pro days",
    FREEZE: "Streak freezes",
    COSMETIC: "Cosmetic",
}

ATTEMPT_WINDOW = 600.0
MAX_ATTEMPTS = 8

_tries_lock = threading.Lock()
_tries = {}


MAX_FREEZE_STACK = 9

OK = "ok"
MESSAGES = {
    "unknown": "That code isn't valid.",
    "off": "That code is no longer active.",
    "early": "That code isn't live yet.",
    "over": "That code has expired.",
    "spent": "That code has been fully claimed.",
    "already": "You've already redeemed that code.",
    "race": "That code has just been fully claimed.",
    "failed": "We couldn't apply that code. Nothing was changed.",
}

def normalise(raw):
    return re.sub(r"\s+", "", (raw or "")).upper()[:32]

def make_code(length=10):
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def find(raw):
    code = normalise(raw)
    if not code:
        return None
    return db.session.execute(
        db.select(RedeemCode).filter_by(code=code)).scalar_one_or_none()


def _claim_slot(row):
    if not row.max_uses:
        db.session.execute(
            db.update(RedeemCode).where(RedeemCode.id == row.id)
            .values(used_count=RedeemCode.used_count + 1)
            .execution_options(synchronize_session=False))
        return True

    result = db.session.execute(
        db.update(RedeemCode)
        .where(RedeemCode.id == row.id,
               RedeemCode.used_count < row.max_uses)
        .values(used_count=RedeemCode.used_count + 1)
        .execution_options(synchronize_session=False))
    return result.rowcount == 1


def _pay(user, row):
    if row.reward == COINS:
        economy.earn(user, row.amount, "redeem", str(row.id))
        return "%d coins" % row.amount

    if row.reward == XP:
        award_xp(user, row.amount, "redeem", str(row.id))
        return "%d XP" % row.amount

    if row.reward == FREEZE:
        user.streak_freezes = min(MAX_FREEZE_STACK,
                                  (user.streak_freezes or 0) + row.amount)
        return "%d streak freeze%s" % (row.amount,
                                       "" if row.amount == 1 else "s")

    if row.reward == COSMETIC:
        from . import cosmetics
        if not cosmetics.grant(user, row.note.strip(), source="redeem"):
            return None
        return "a cosmetic"

    if row.reward == PRO:
        from .billing.service import grant_manual
        days = max(1, row.amount)
        sub = grant_manual(user, row.created_by or user, months=1,
                           note="redeem:%s" % row.code)
        sub.current_period_end = _utcnow() + timedelta(days=days)
        return "%d days of Pro" % days

    return None

def redeem(user, raw):
    row = find(raw)
    if row is None:
        return False, None, MESSAGES['unknown']

    state = row.window
    if state != "live":
        return False, row, MESSAGES.get(state, MESSAGES["off"])

    try:
        with db.session.begin_nested():
            db.session.add(RedeemUse(code_id=row.id, user_id=user.id,
                                     reward=row.reward, amount=row.amount))
    except IntegrityError:
        return False, row, MESSAGES["already"]

    if row is None:
        return False, None, MESSAGES["unknown"]
    forget_attempts(user)

    if not _claim_slot(row):
        db.session.rollback()
        return False, row, MESSAGES["race"]

    got = _pay(user, row)
    if got is None:
        db.session.rollback()
        return False, row, MESSAGES["failed"]

    db.session.commit()

    notify.send_once(user, "redeem", str(row.id),
                     "Code redeemed: %s" % got,
                     body=row.note or "Enjoy.")
    return True, row, "Redeemed - you got %s." % got


def recent(limit=50, only_active=False):
    stmt = db.select(RedeemCode).order_by(RedeemCode.created_at.desc())
    if only_active:
        stmt = stmt.where(RedeemCode.is_active.is_(True))
    return db.session.execute(stmt.limit(limit)).scalars().all()


def uses_for(code_id, limit=100):
    return db.session.execute(
        db.select(RedeemUse).where(RedeemUse.code_id == code_id)
        .order_by(RedeemUse.created_at.desc()).limit(limit)).scalars().all()

def attempt_allowed(user):
    now = _time.monotonic()
    with _tries_lock:
        seen = [t for t in _tries.get(user.id, ()) if now - t < ATTEMPT_WINDOW]
        if len(seen) >= MAX_ATTEMPTS:
            _tries[user.id] = seen
            return False
        seen.append(now)
        _tries[user.id] = seen
        if len(_tries) > 4096:
            for uid in [k for k, v in _tries.items()
                        if not v or now - v[-1] > ATTEMPT_WINDOW]:
                _tries.pop(uid, None)
    return True

def forget_attempts(user):
    with _tries_lock:
        _tries.pop(user.id, None)

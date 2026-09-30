import hashlib
import hmac
import secrets
from collections import defaultdict
from datetime import timedelta

from .models import (API_SCOPES, DEFAULT_SCOPES, MAX_KEYS_PER_USER, ApiKey,
                     _utcnow, db)

PREFIX = "piko_sk_"
SECRET_BYTES = 32
PREFIX_LEN = 12
TOUCH_EVERY = timedelta(minutes=5)

def _hash(raw):
    return hashlib.sha256((raw or "").encode("utf-8")).hexdigest()

def mint(user, name="", scopes=None, days=None):
    live = [k for k in user_keys(user) if k.is_live]
    if len(live) >= MAX_KEYS_PER_USER:
        raise ValueError("You already have %d live keys." % MAX_KEYS_PER_USER)

    wanted = [s for s in (scopes or DEFAULT_SCOPES) if s in API_SCOPES]
    if not wanted:
        wanted = list(DEFAULT_SCOPES)

    secret = secrets.token_urlsafe(SECRET_BYTES)
    raw = PREFIX + secret
    row = ApiKey(
        user_id=user.id,
        name=(name or "Untitled key")[:80],
        prefix=secret[:PREFIX_LEN],
        key_hash=_hash(raw),
        scopes=wanted,
        expires_at=(_utcnow() + timedelta(days=int(days))) if days else None,
    )
    db.session.add(row)
    db.session.commit()
    return row, raw

def resolve(raw):
    if not raw or not raw.startswith(PREFIX):
        return None
    secret = raw[len(PREFIX):]
    if len(secret) < PREFIX_LEN:
        return None

    row = db.session.execute(
        db.select(ApiKey).filter_by(prefix=secret[:PREFIX_LEN])
    ).scalar_one_or_none()
    if row is None:
        return None
    if not hmac.compare_digest(row.key_hash, _hash(raw)):
        return None
    if not row.is_live:
        return None
    if row.user is None or row.user.is_suspended:
        return None
    return row

# Counts waiting to be written, keyed by api_key id. A flush() without a
# commit is rolled back at teardown, so buffering here is what stops the
# counter losing almost everything between periodic writes.
_pending = defaultdict(int)


def touch(row, ip=""):
    """Record a call. Writes at most once per TOUCH_EVERY per key.

    A write on every request would roughly double the database traffic of
    the whole API for a number nobody reads in real time, so counts batch in
    memory and land with the periodic write. That makes this per-process and
    approximate: a restart drops up to TOUCH_EVERY of counts, and under
    gunicorn each worker keeps its own buffer.
    """
    _pending[row.id] += 1

    fresh = (row.last_used_at is not None
             and _utcnow() - row.last_used_at <= TOUCH_EVERY)
    if fresh:
        return

    row.requests = (row.requests or 0) + _pending.pop(row.id, 0)
    row.last_used_at = _utcnow()
    row.last_ip = (ip or "")[:64]
    db.session.commit()

def revoke(row):
    if row.revoked_at is None:
        row.revoked_at = _utcnow()
        db.session.commit()


def user_keys(user):
    return db.session.execute(
        db.select(ApiKey).filter_by(user_id=user.id)
        .order_by(ApiKey.created_at.desc())
    ).scalars().all()


def masked(row):
    return PREFIX + row.prefix + "\u2026"
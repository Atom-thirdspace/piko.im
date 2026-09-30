import hashlib
import secrets
from datetime import timedelta
from ..models import (AuthorInvite, AuthorInviteUse, _utcnow, db)

TOKEN_BYTES = 32
DEFAULT_TTL_DAYS = 14
MAX_TTL_DAYS = 90
MAX_USES = 50

def _hash(raw):
    return hashlib.sha256((raw or "").encode("utf-8")).hexdigest()

def create_invite(admin, email=None, note="", max_uses = 1, ttl_days = DEFAULT_TTL_DAYS):
    raw = secrets.token_urlsafe(TOKEN_BYTES)
    row = AuthorInvite(
        token_hash=_hash(raw),
        email=((email or "").strip().lower() or None),
        note=(note or "")[:200],
        invited_by_id=admin.id,
        max_uses=max(1, min(int(max_uses or 1), MAX_USES)),
        expires_at=_utcnow() + timedelta(days=max(1, min(int(ttl_days or 1), MAX_TTL_DAYS))),
    )
    db.session.add(row)
    db.session.commit()
    return row, raw


def find_invite(raw):
    if not raw:
        return None
    return db.session.execute(
        db.select(AuthorInvite).filter_by(token_hash = _hash(raw))
    ).scalar_one_or_none()

def refusal(invite, user):
    if invite is None:
        return "The invite link is not valid"
    if invite.revoked_at is not None:
        return "The invite has been withdrawn"
    if invite.expires_at <= _utcnow():
        return "This invite has expired."
    if invite.uses >= invite.max_uses:
        return "This invite has already been used."
    if invite.email and (user.email or "").lower() != invite.email:
        return "This invite was issued to a different email address."
    if not user.email_verified_at:
        return "Confirm your email address first, then open this link again."
    return None

def accept(invite, user):
    if user.is_author:
        return False

    already = db.session.execute(
        db.select(AuthorInviteUse).filter_by(invite_id=invite.id, user_id=user.id)
    ).scalar_one_or_none()
    if already is not None:
        return False

    user.is_author = True
    user.author_since = _utcnow()
    invite.uses += 1
    db.session.add(AuthorInviteUse(invite_id=invite.id, user_id=user.id))
    db.session.commit()
    return True


def revoke(invite):
    if invite.revoked_at is None:
        invite.revoked_at = _utcnow()
        db.session.commit()
from datetime import timedelta
from .models import Submission, _utcnow, db

SUBMIT_PER_MINUTE = 6
SUBMIT_PER_HOUR = 80


def submissions_since(user, since):
    return db.session.execute(
        db.select(db.func.count()).select_from(Submission)
        .where(Submission.user_id == user.id, Submission.created_at >= since)
    ).scalar() or 0


def submit_block_reason(user):
    now = _utcnow()
    if submissions_since(user, now - timedelta(minutes=1)) >= SUBMIT_PER_MINUTE:
        return ("You are submitting very fast. Wait a few seconds - each run "
                "starts a fresh container.")

    if submissions_since(user, now - timedelta(hours=1)) >= SUBMIT_PER_HOUR:
        return "That is a lot of submissions this hour. Take a break."
    return None

from datetime import timedelta
from .models import ScratchRun, Submission, _utcnow, db

SUBMIT_PER_MINUTE = 6
SUBMIT_PER_HOUR = 80

# Runs are cheaper to allow than submissions - they are how you learn - but
# each one is still a container, so they are not free.
RUN_PER_MINUTE = 15
RUN_PER_HOUR = 200


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


def runs_since(user, since):
    return db.session.execute(
        db.select(db.func.count()).select_from(ScratchRun)
        .where(ScratchRun.user_id == user.id, ScratchRun.created_at >= since)
    ).scalar() or 0


def run_block_reason(user):
    now = _utcnow()
    if runs_since(user, now - timedelta(minutes=1)) >= RUN_PER_MINUTE:
        return "Slow down a moment - every run starts a container."
    if runs_since(user, now - timedelta(hours=1)) >= RUN_PER_HOUR:
        return "That is a lot of runs this hour. Take a break."
    return None

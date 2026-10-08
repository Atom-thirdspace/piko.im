from datetime import timedelta
from .models import ScratchRun, Submission, _utcnow, db

SUBMIT_PER_MINUTE = 6
SUBMIT_PER_HOUR = 80

# Runs are cheaper to allow than submissions - they are how you learn - but
# each one is still a container, so they are not free.
RUN_PER_MINUTE = 15
RUN_PER_HOUR = 200

PRO_SUBMIT_PER_MINUTE = 20
PRO_SUBMIT_PER_HOUR = 400
PRO_RUN_PER_MINUTE = 60
PRO_RUN_PER_HOUR = 2000

def _limits(user):
    from .billing.service import is_pro
    if is_pro(user):
        return {"submit_min": PRO_SUBMIT_PER_MINUTE,
                "submit_hour": PRO_SUBMIT_PER_HOUR,
                "run_min": PRO_RUN_PER_MINUTE,
                "run_hour": PRO_RUN_PER_HOUR, "pro": True}
    return {"submit_min": SUBMIT_PER_MINUTE, "submit_hour": SUBMIT_PER_HOUR,
            "run_min": RUN_PER_MINUTE, "run_hour": RUN_PER_HOUR, "pro": False}

def submissions_since(user, since):
    return db.session.execute(
        db.select(db.func.count()).select_from(Submission)
        .where(Submission.user_id == user.id, Submission.created_at >= since)
    ).scalar() or 0

def submit_block_reason(user):
    now = _utcnow()
    caps = _limits(user)
    if submissions_since(user, now - timedelta(minutes=1)) >= caps["submit_min"]:
        return ("You are submitting very fast. Wait a few seconds - each run "
                "starts a fresh container.")
    if submissions_since(user, now - timedelta(hours=1)) >= caps["submit_hour"]:
        if caps["pro"]:
            return "That is a lot of submissions this hour. Take a break."
        return ("That is a lot of submissions this hour. Pro raises this "
                "limit, or take a break and come back.")
    return None

def runs_since(user, since):
    return db.session.execute(
        db.select(db.func.count()).select_from(ScratchRun)
        .where(ScratchRun.user_id == user.id, ScratchRun.created_at >= since)
    ).scalar() or 0

def run_block_reason(user):
    now = _utcnow()
    caps = _limits(user)
    if runs_since(user, now - timedelta(minutes=1)) >= caps["run_min"]:
        return "Slow down a moment - every run starts a container."
    if runs_since(user, now - timedelta(hours=1)) >= caps["run_hour"]:
        if caps["pro"]:
            return "That is a lot of runs this hour. Take a break."
        return ("You have used this hour's runs. Pro lifts the cap, or wait "
                "for the hour to roll over.")
    return None

def run_headroom(user):
    now = _utcnow()
    caps = _limits(user)
    return max(0, min(caps["run_min"] - runs_since(user, now - timedelta(minutes=1)),
                      caps["run_hour"] - runs_since(user, now - timedelta(hours=1))))
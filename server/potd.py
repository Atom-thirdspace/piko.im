import random
from datetime import datetime, time, timedelta, timezone

from .memo import per_request
from .models import (PUBLISHED, Problem, ProblemSolve, User, _utcnow, db)
from .progress import award_xp

BONUS_XP = 25

SALT = 20260101

FASTEST_SHOWN = 5


def potd_date():
    # UTC, not the viewer's local date: a shared problem has to be shared.
    return _utcnow().astimezone(timezone.utc).date()


def _day_bounds(day):
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


@per_request(lambda day=None: day or potd_date())
def problem_for(day=None):
    day = day or potd_date()
    ids = db.session.execute(
        db.select(Problem.id).where(Problem.status == PUBLISHED)
        .order_by(Problem.id)).scalars().all()
    if not ids:
        return None
    order = list(ids)
    random.Random(SALT).shuffle(order)
    return db.session.get(Problem, order[day.toordinal() % len(order)])


def stats(problem, day=None):
    if problem is None:
        return {"solvers": 0, "fastest": []}
    lo, hi = _day_bounds(day or potd_date())
    solvers = db.session.execute(
        db.select(db.func.count()).select_from(ProblemSolve)
        .where(ProblemSolve.problem_id == problem.id,
               ProblemSolve.solved_at >= lo,
               ProblemSolve.solved_at < hi)).scalar() or 0
    rows = db.session.execute(
        db.select(User.username, User.avatar_url, ProblemSolve.seconds)
        .join(ProblemSolve, ProblemSolve.user_id == User.id)
        .where(ProblemSolve.problem_id == problem.id,
               ProblemSolve.solved_at >= lo, ProblemSolve.solved_at < hi)
        .order_by(ProblemSolve.seconds).limit(FASTEST_SHOWN)).all()
    return {"solvers": solvers,
            "fastest": [{"username": r.username, "avatar_url": r.avatar_url,
                         "seconds": r.seconds} for r in rows]}


def award_if_today(user, problem):
    day = potd_date()
    todays = problem_for(day)
    if todays is None or todays.id != problem.id:
        return 0
    return award_xp(user, BONUS_XP, "potd", day.isoformat())["awarded"]


def card(user=None, day=None):
    day = day or potd_date()
    problem = problem_for(day)
    if problem is None:
        return None
    solved = False
    if user is not None:
        solved = db.session.execute(
            db.select(ProblemSolve.id)
            .filter_by(user_id=user.id, problem_id=problem.id)).scalar() is not None
    return {"day": day, "problem": problem, "solved": solved,
            "bonus": BONUS_XP, **stats(problem, day)}

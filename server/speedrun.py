from .models import (ProblemSolve, SpeedAttempt, SpeedRecord, _utcnow, db)
MAX_SECONDS = 60*60

def best(user, problem):
    if user is None:
        return None
    return db.session.execute(
        db.select(SpeedRecord).filter_by(user_id=user.id,
                                         problem_id=problem.id)
    ).scalar_one_or_none()

def open_attempt(user):
    return db.session.execute(
                db.select(SpeedAttempt).where(SpeedAttempt.user_id == user.id,
                                      SpeedAttempt.finished_at.is_(None))
        .order_by(SpeedAttempt.started_at.desc()).limit(1)
    ).scalar_one_or_none()

def eligible(user, problem):
    return db.session.execute(
        db.select(ProblemSolve.id).filter_by(user_id=user.id,
                                             problem_id=problem.id)).scalar()

def start(user, problem):
    if not eligible(user, problem):
        return None, "Solve it once before you race it."

    existing = open_attempt(user)
    if existing is not None:
        if existing.problem_id == problem.id:
            return existing, None
        abandon(existing)
    row = SpeedAttempt(user_id=user.id, problem_id=problem.id)
    db.session.add(row)
    db.session.commit()
    return row, None

def abandon(attempt):
    attempt.finished_at = _utcnow()
    attempt.seconds = None
    db.session.commit()


def settle(user, submission):
    attempt = open_attempt(user)
    if attempt is None or attempt.problem_id != submission.problem_id:
        return None

    elapsed = int((submission.created_at - attempt.started_at).total_seconds())
    attempt.finished_at = _utcnow()
    attempt.submission_id = submission.id

    if elapsed < 0 or elapsed > MAX_SECONDS:
        attempt.seconds = None
        db.session.commit()
        return None

    attempt.seconds = elapsed
    record = db.session.execute(
        db.select(SpeedRecord).filter_by(user_id=user.id,
                                         problem_id=submission.problem_id)
    ).scalar_one_or_none()

    beat = record is None or elapsed < record.seconds
    previous = record.seconds if record else None

    if record is None:
        db.session.add(SpeedRecord(user_id=user.id,
                                   problem_id=submission.problem_id,
                                   seconds=elapsed,
                                   submission_id=submission.id))
    elif beat:
        record.seconds = elapsed
        record.submission_id = submission.id
        record.set_at = _utcnow()

    db.session.commit()

    if not beat:
        return {"seconds": elapsed, "record": False, "previous": previous}

    from . import economy
    economy.earn(user, economy.SPEED_RECORD_COINS, "speed",
                 "%d:%d" % (submission.problem_id, elapsed))
    return {"seconds": elapsed, "record": True, "previous": previous}

def leaderboard(problem, limit=20):
    from .models import User
    rows = db.session.execute(
        db.select(SpeedRecord, User).join(User, User.id == SpeedRecord.user_id)
        .where(SpeedRecord.problem_id == problem.id,
               User.show_on_leaderboard.is_(True))
        .order_by(SpeedRecord.seconds.asc(), SpeedRecord.set_at.asc())
        .limit(limit)).all()
    return [{"rank": i, "user": u, "seconds": r.seconds, "at": r.set_at}
            for i, (r, u) in enumerate(rows, 1)]

def mine(user, limit=20):
    from .models import Problem
    rows = db.session.execute(
        db.select(SpeedRecord, Problem)
        .join(Problem, Problem.id == SpeedRecord.problem_id)
        .where(SpeedRecord.user_id == user.id)
        .order_by(SpeedRecord.set_at.desc()).limit(limit)).all()
    return [{"problem": p, "seconds": r.seconds, "at": r.set_at}
            for r, p in rows]
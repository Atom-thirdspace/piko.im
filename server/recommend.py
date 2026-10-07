from .models import PUBLISHED, Problem, db, ProblemSolve

LADDER = ("easy", "medium", "hard")

def _solved_ids(user):
    return set(db.session.execute(
        db.select(ProblemSolve.problem_id)
        .where(ProblemSolve.user_id == user.id)).scalars())


def _target_difficulty(solved_count):
    if solved_count < 5:
        return "easy"
    if solved_count < 25:
        return "medium"
    return "hard"


def _by_topic(user):
    """Solve counts per topic, including topics never touched.

    Counting only what they have solved leaves every untouched topic out of
    the dict, so "your thinnest topic" could never name one.
    """
    counts = {t: 0 for t in db.session.execute(
        db.select(db.distinct(Problem.topic))
        .where(Problem.status == PUBLISHED, Problem.topic.isnot(None))
    ).scalars()}
    rows = db.session.execute(
        db.select(Problem.topic, db.func.count())
        .select_from(ProblemSolve)
        .join(Problem, Problem.id == ProblemSolve.problem_id)
        .where(ProblemSolve.user_id == user.id, Problem.topic.isnot(None))
        .group_by(Problem.topic)).all()
    counts.update({topic: n for topic, n in rows})
    return counts

def next_problem(user):
    if user is None:
        return None

    live = db.session.execute(
        db.select(Problem.id).where(Problem.status == PUBLISHED).limit(1)
    ).scalar()
    if live is None:
        return None

    solved = _solved_ids(user)
    strength = _by_topic(user)
    target = _target_difficulty(len(solved))

    def pick(stmt, reason):
        row = db.session.execute(stmt.limit(1)).scalars().first()
        return {"problem": row, "reason": reason} if row else None

    base = db.select(Problem).where(Problem.status == PUBLISHED)
    if solved:
        base = base.where(Problem.id.notin_(solved))

    interests = [k for k in (user.interest_keys or []) if strength.get(k, 0) < 3]
    for topic in interests:
        hit = pick(base.where(Problem.topic == topic,
                              Problem.difficulty == target)
                   .order_by(Problem.id), "you picked %s when you signed up" % topic)
        if hit:
            return hit

    if strength:
        weakest = min(sorted(strength), key=strength.get)
        hit = pick(base.where(Problem.topic == weakest).order_by(Problem.id),
                   "your thinnest topic is %s" % weakest)
        if hit:
            return hit

    # One ordered query rather than a round trip per rung: the CASE ranks
    # the target difficulty first, then the rest of the ladder.
    rung = {d: i for i, d in enumerate([target]
                                       + [d for d in LADDER if d != target])}
    row = db.session.execute(
        base.order_by(db.case(rung, value=Problem.difficulty, else_=99),
                      Problem.id).limit(1)).scalars().first()
    if row is not None:
        return {"problem": row,
                "reason": "a %s one to keep moving" % row.difficulty}
    return None 
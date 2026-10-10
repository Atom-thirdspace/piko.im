from .models import TopicMastery, _utcnow, db

HALF_LIFE_DAYS = 45.0

SOLVE_POINTS = {"easy": 8, "medium": 16, "hard": 28}
LESSON_POINTS = 4
QUIZ_POINTS = 6
ARENA_POINTS = 2      

BANDS = (
    (300, "mastered"),
    (150, "strong"),
    (75, "solid"),
    (25, "learning"),
    (0, "touched"),
)

def decayed(points, updated_at, now=None):
    now = now or _utcnow()
    days = max(0.0, (now - updated_at).total_seconds() / 86400.0)
    return float(points) * (0.5 ** (days / HALF_LIFE_DAYS))

def band(value):
    for threshold, name in BANDS:
        if value >= threshold:
            return name
    return "touched"

def add(user, topic, points):
    if user is None or not topic or points <= 0:
        return None

    now = _utcnow()
    row = db.session.execute(
        db.select(TopicMastery).filter_by(user_id=user.id, topic=topic)
    ).scalar_one_or_none()

    if row is None:
        row = TopicMastery(user_id=user.id, topic=topic, points=float(points),
                           peak=float(points), updated_at=now)
        db.session.add(row)
    else:
        row.points = decayed(row.points, row.updated_at, now) + points
        row.peak = max(row.peak or 0.0, row.points)
        row.updated_at = now

    db.session.commit()
    return row

def for_user(user):
    if user is None:
        return []
    now = _utcnow()
    rows = db.session.execute(
        db.select(TopicMastery).where(TopicMastery.user_id == user.id)
    ).scalars().all()

    out = []
    for row in rows:
        value = decayed(row.points, row.updated_at, now)
        out.append({
            "topic": row.topic,
            "value": round(value, 1),
            "band": band(value),
            "peak": round(row.peak or value, 1),
            "fraction": min(1.0, value / 300.0),
            "faded": (row.peak or 0) > 0 and value < (row.peak or 0) * 0.7,
            "updated_at": row.updated_at,
        })
    out.sort(key=lambda r: -r["value"])
    return out

def rusty(user, limit = 3):
    return [r for r in for_user(user) if r["faded"] and r["peak"] >= 25][:limit]

def record_solve(user, problem):
    if problem.topic:
        add(user, problem.topic, SOLVE_POINTS.get(problem.difficulty, 8))


def record_lesson(user, lesson):
    topic = (lesson.topic if getattr(lesson, "topic", None)
             else (lesson.unit.topic if lesson.unit else None))
    if topic:
        add(user, topic, QUIZ_POINTS if lesson.kind == "quiz" else LESSON_POINTS)

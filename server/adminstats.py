from datetime import timedelta

from .models import (Lesson, LessonProgress, Problem, ProblemSolve,
                     PUBLISHED, REVIEW, DRAFT, Submission, Subscription,
                     Track, Unit, User, XpEvent, _utcnow, db)

MONTHS = 12
ACTIVE_WINDOW_DAYS = 7

FUNNEL_RAMP = ("#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281")

def _scalar(stmt):
    return db.session.execute(stmt).scalar() or 0

def _count(model, *where):
    stmt = db.select(db.func.count()).select_from(model)
    if where:
        stmt = stmt.where(*where)
    return _scalar(stmt)

def headline():
    now = _utcnow()
    since = now - timedelta(days=ACTIVE_WINDOW_DAYS)
    active = _scalar(
        db.select(db.func.count(db.distinct(XpEvent.user_id)))
        .where(XpEvent.created_at >= since))
    accepted = _count(Submission, Submission.verdict == "accepted")
    submissions = _count(Submission)
    return {
        "users": _count(User),
        "active": active,
        "problems": _count(Problem, Problem.status == PUBLISHED),
        "lessons": _count(Lesson, Lesson.status == PUBLISHED),
        "submissions": submissions,
        "accept_rate": (accepted * 100.0 / submissions) if submissions else 0.0,
        "solves": _count(ProblemSolve),
        "lessons_done": _count(LessonProgress),
    }

def funnel():
    did_something = db.select(XpEvent.user_id).where(
        XpEvent.user_id == User.id)
    subscribed = db.select(Subscription.user_id).where(
        Subscription.user_id == User.id,
        Subscription.status.in_(("active", "trialing")))

    conditions = []
    stages = []
    for label, extra in (
        ("Signed up", None),
        ("Confirmed their email", User.email_verified_at.isnot(None)),
        ("Finished onboarding", User.onboarded_at.isnot(None)),
        ("Earned any XP", did_something.exists()),
        ("Subscribed", subscribed.exists()),
    ):
        if extra is not None:
            conditions.append(extra)
        stages.append((label, _count(User, *conditions) if conditions
                       else _count(User)))

        top = stages[0][1]
        rows, previous = [], top
        for i, (label, value) in enumerate(stages):
            rows.append({
                "label": label,
                "value": value,
                "percent": value * 100.0 / top,
                "step": (value * 100.0 / previous) if previous else None,
                "colour": FUNNEL_RAMP[i],
            })
            previous = value or None
        return rows

def _month_buckets(column, *where):
    month = db.func.date_trunc("month", db.func.timezone("UTC", column))
    stmt = db.select(month.label("m"), db.func.count()).group_by("m")
    if where:
        stmt = stmt.where(*where)
    return {row[0]: row[1] for row in db.session.execute(stmt).all()}

def _recent_months(n=MONTHS):
    now = _utcnow()
    cursor = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    out = [cursor]
    for _ in range(n - 1):
        cursor = (cursor - timedelta(days=1)).replace(day=1)
        out.append(cursor)
    return list(reversed(out))

def _key(buckets, month):
    for k, v in buckets.items():
        if k is not None and (k.year, k.month) == (month.year, month.month):
            return v
    return 0

def signups_series(n=MONTHS):
    buckets = _month_buckets(User.created_at)
    return [{"label": m.strftime("%b"), "full": m.strftime("%b %Y"),
             "value": _key(buckets, m)} for m in _recent_months(n)]


def submissions_series(n=MONTHS):
    total = _month_buckets(Submission.created_at)
    ok = _month_buckets(Submission.created_at,
                        Submission.verdict == "accepted")
    rows = []
    for m in _recent_months(n):
        t,a = _key(total, m), _key(ok, m)
        rows.append({"label": m.strftime("%b"), "full": m.strftime("%b %Y"),
                     "accepted": a, "other": max(0, t - a), "total": t})
    return rows

def columns(rows, value_keys, width=680, height=170, pad=26, gap=2):
    plot_h = height - pad
    top = max([sum(r[k] for k in value_keys) for r in rows] + [1])
    step = width / max(len(rows), 1)
    bar_w = max(6.0, step - 10)

    bars = []
    for i, row in enumerate(rows):
        x = i * step + (step - bar_w) / 2
        y = float(plot_h)
        stack = []
        for key in value_keys:
            value = row[key]
            h = (value / top) * (plot_h - 4)
            if h > 0:
                y -= h
                stack.append({"key": key, "value": value, "x": round(x, 2),
                              "y": round(y, 2), "w": round(bar_w, 2),
                              "h": round(max(h - gap, 1), 2)})
                y -= 0  # the gap is taken out of the height, not the offset
        bars.append({"row": row, "x": round(x, 2), "w": round(bar_w, 2),
                     "label_x": round(x + bar_w / 2, 2), "stack": stack,
                     "total": sum(row[k] for k in value_keys)})

    ticks = [{"value": int(top * f), "y": round(plot_h - f * (plot_h - 4), 2)}
             for f in (0.0, 0.5, 1.0)]
    return {"bars": bars, "ticks": ticks, "width": width, "height": height,
            "plot_h": plot_h, "top": top}


def diverging(rows, up_key, down_key, width=680, height=190, pad=26, gap=2):

    plot_h = height - pad
    mid = plot_h / 2
    top = max([max(r[up_key], r[down_key]) for r in rows] + [1])
    step = width / max(len(rows), 1)
    bar_w = max(6.0, step - 10)

    bars = []
    for i, row in enumerate(rows):
        x = i * step + (step - bar_w) / 2
        up_h = (row[up_key] / top) * (mid - 6)
        down_h = (row[down_key] / top) * (mid - 6)
        bars.append({
            "row": row, "x": round(x, 2), "w": round(bar_w, 2),
            "label_x": round(x + bar_w / 2, 2),
            "up": {"y": round(mid - up_h - gap / 2, 2),
                   "h": round(max(up_h, 0), 2), "value": row[up_key]},
            "down": {"y": round(mid + gap / 2, 2),
                     "h": round(max(down_h, 0), 2), "value": row[down_key]},
        })
    return {"bars": bars, "mid": round(mid, 2), "width": width,
            "height": height, "top": top}

def verdict_mix(limit=8):
    rows = db.session.execute(
        db.select(Submission.verdict, db.func.count())
        .group_by(Submission.verdict)
        .order_by(db.func.count().desc()).limit(limit)).all()
    total = sum(n for _, n in rows) or 1
    return [{"label": (v or "unknown").replace("_", " "), "value": n,
             "percent": n * 100.0 / total} for v, n in rows]


def content_pipeline():
    out = []
    for name, model in (("Courses", Track), ("Units", Unit),
                        ("Lessons", Lesson), ("Problems", Problem)):
        out.append({
            "label": name,
            "draft": _count(model, model.status == DRAFT),
            "review": _count(model, model.status == REVIEW),
            "published": _count(model, model.status == PUBLISHED),
        })

    return out

def judge_health():
    from .models import JudgeJob, ScratchRun
    day_ago = _utcnow() - timedelta(days=1)
    return {
        "queued": _count(JudgeJob, JudgeJob.status == "queued"),
        "running": _count(JudgeJob, JudgeJob.status == "running"),
        "failed": _count(JudgeJob, JudgeJob.status == "failed"),
        "done_24h": _count(JudgeJob, JudgeJob.status == "done",
                           JudgeJob.finished_at >= day_ago),
        "scratch_runs": _count(ScratchRun),
    }


def engagement():
    streaks = _scalar(db.select(db.func.count()).select_from(User)
                      .where(User.streak_days >= 3))
    best = _scalar(db.select(db.func.max(User.streak_best)))
    xp = _scalar(db.select(db.func.coalesce(db.func.sum(XpEvent.amount), 0)))
    return {"on_a_streak": streaks, "best_streak": best, "xp_awarded": xp}
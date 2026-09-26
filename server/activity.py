from datetime import timedelta
from .models import XpEvent, _utcnow, db
from .progress import user_today

WEEKS = 26

def _local_date(user):
    return db.func.date(db.func.timezone(user.timezone or "UTC", XpEvent.created_at))

def daily_xp(user, days = 200):
    day = _local_date(user)
    rows = db.session.execute(
        db.select(day.label("day"), db.func.sum(XpEvent.amount).label("xp"))
        .where(XpEvent.user_id == user.id,
               XpEvent.created_at >= _utcnow() - timedelta(days=days + 2))
        .group_by(day)
    ).all()
    return {d: int(n or 0) for d, n in rows}

def _level(xp, goal):
    if xp <=0:
        return 0
    goal = max(goal or 30, 10)
    if xp < goal * 0.5:
        return 1
    if xp < goal:
        return 2
    if xp < goal * 2:
        return 3
    return 4

def heatmap(user, weeks = WEEKS):
    today = user_today(user)
    start = today - timedelta(days=today.weekday()) - timedelta(weeks=weeks - 1)
    daily = daily_xp(user, days=weeks * 7 + 7)
    goal = user.daily_goal_xp or 30

    columns = []
    for w in range(weeks):
        column = []
        for d in range(7):
            day = start + timedelta(weeks=w, days=d)
            xp = daily.get(day, 0)
            column.append({"date": day, "xp": xp,
                           "level": _level(xp, goal),
                           "future": day > today})
        columns.append(column)

    active = sum(1 for v in daily.values() if v > 0)
    return {"columns": columns, "start": start, "end": today,
            "total_xp": sum(daily.values()), "active_days": active,
            "today_xp": daily.get(today, 0), "goal": goal}
 
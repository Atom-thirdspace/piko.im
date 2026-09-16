from datetime import timedelta
from math import isqrt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from sqlalchemy.exc import IntegrityError
from .models import User, XpEvent, _utcnow, db

XP_PER_LEVEL_STEP = 50

def level_for_xp(xp):
    return (isqrt(4 * (max(xp, 0) // XP_PER_LEVEL_STEP) + 1) + 1) // 2

def xp_for_level(level):
    return XP_PER_LEVEL_STEP * level * (level - 1)

def level_progress(xp):
    level = level_for_xp(xp)
    floor, ceiling = xp_for_level(level), xp_for_level(level + 1)
    return {"level": level, "xp": xp, "level_floor": floor, "level_ceiling": ceiling,
            "into_level": xp - floor, "level_span": ceiling - floor}

def user_today(user):
    try:
        tz = ZoneInfo(user.timezone or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("UTC")
    return _utcnow().astimezone(tz).date()

def touch_streak(user, today):
    last = user.last_active_date
    if last == today:
        return False
    user.streak_days = (user.streak_days or 0) + 1 if last == today - timedelta(days=1) else 1
    user.streak_best = max(user.streak_best or 0, user.streak_days)
    user.last_active_date = today
    return True

def award_xp(user, amount, reason, ref):
    before = user.xp_total or 0
    try:
        with db.session.begin_nested():
            db.session.add(XpEvent(user_id=user.id, amount=amount, reason=reason, ref=ref))
    except IntegrityError:
        return {"awarded": 0, "leveled_up": False, **level_progress(before)}
    db.session.execute(
        db.update(User)
        .where(User.id == user.id)
        .values(xp_total=User.xp_total + amount)
        .execution_options(synchronize_session=False)
    )
    db.session.refresh(user, attribute_names=["xp_total"])
    touch_streak(user, user_today(user))

    after = user.xp_total
    return {"awarded": amount, "leveled_up": level_for_xp(after) > level_for_xp(before),
            **level_progress(after)}
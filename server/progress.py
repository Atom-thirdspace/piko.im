from datetime import timedelta
from math import isqrt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from sqlalchemy.exc import IntegrityError
from .models import User, XpEvent, _utcnow, db

XP_PER_LEVEL_STEP = 50
MAX_FREEZES = 3
MAX_FROZEN_GAP = 2

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
    streak = touch_streak(user, user_today(user))
    after = user.xp_total
    return {"awarded": amount,
            "leveled_up": level_for_xp(after) > level_for_xp(before),
            "streak": streak,
            **level_progress(after)}

def grant_monthly_freeze(user, today):
    granted = user.freezes_granted_on
    if granted is not None and (granted.year, granted.month) == (today.year, today.month):
        return 0

    user.freezes_granted_on = today
    if (user.streak_freezes or 0) >= MAX_FREEZES:
        return 0
    user.streak_freezes = (user.streak_freezes or 0) + 1
    return 1


def _missed_days(last, today):
    if last is None or today <= last:
        return 0
    return (today - last).days - 1

def touch_streak(user, today):
    from .models import StreakFreezeUse, db
    last = user.last_active_date
    if last == today:
        return {"changed": False, "continued": False, "frozen": 0, "reset": False,
                "days": user.streak_days or 0,
                "freezes_left": user.streak_freezes or 0}

    granted = grant_monthly_freeze(user, today)
    missed = _missed_days(last, today)
    frozen = 0
    reset = False

    if last is None:
        user.streak_days = 1
    elif missed == 0:
        user.streak_days = (user.streak_days or 0) + 1
    elif missed <= MAX_FROZEN_GAP and (user.streak_freezes or 0) >= missed:
        # Spend one freeze per missed day and carry the streak through.
        user.streak_freezes -= missed
        for i in range(missed):
            db.session.add(StreakFreezeUse(
                user_id=user.id, covered_date=last + timedelta(days=i + 1)))
        frozen = missed
        user.streak_days = (user.streak_days or 0) + 1
    else:
        user.streak_days = 1
        reset = True

    # Every path, not just the reset one - otherwise a best is never set.
    user.streak_best = max(user.streak_best or 0, user.streak_days)
    user.last_active_date = today
    return {"changed": True, "continued": missed == 0 and last is not None,
            "frozen": frozen, "reset": reset, "granted": granted,
            "days": user.streak_days, "freezes_left": user.streak_freezes or 0}


def streak_state(user, today):
    last = user.last_active_date
    stored = user.streak_days or 0
    freezes = user.streak_freezes or 0

    if last is None or stored == 0:
        return {"days": 0, "status": "none", "freezes": freezes,
                "at_risk": False, "covered_by": 0}

    if last == today:
        return {"days": stored, "status": "safe", "freezes": freezes,
                "at_risk": False, "covered_by": 0}
    missed = _missed_days(last, today)
    if missed == 0:                       # last active yesterday
        return {"days": stored, "status": "at_risk", "freezes": freezes,
                "at_risk": True, "covered_by": 0}

    if missed <= MAX_FROZEN_GAP and freezes >= missed:
        return {"days": stored, "status": "frozen", "freezes": freezes,
                "at_risk": True, "covered_by": missed}

    return {"days": 0, "status": "broken", "freezes": freezes,
            "at_risk": False, "covered_by": 0, "lost": stored}

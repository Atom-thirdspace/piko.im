import random
from datetime import timedelta

from .models import Rivalry, User, XpEvent, _utcnow, db
from .progress import level_for_xp

LEVEL_WINDOW = 4          
WIN_COINS = 60
DRAW_COINS = 25
GHOST_WIN_COINS = 35

def week_start(day=None):
    day = day or _utcnow().date()
    return day - timedelta(days=day.weekday())


def _window(week):
    from datetime import datetime, time, timezone as tz
    start = datetime.combine(week, time.min, tzinfo=tz.utc)
    return start, start + timedelta(days=7)

def xp_between(user_id, lo, hi):
    return int(db.session.execute(
        db.select(db.func.coalesce(db.func.sum(XpEvent.amount), 0))
        .where(XpEvent.user_id == user_id,
               XpEvent.created_at >= lo, XpEvent.created_at < hi)).scalar() or 0)

def mine(user, week=None):
    week = week or week_start()
    return db.session.execute(
        db.select(Rivalry).where(Rivalry.week == week,
                                 db.or_(Rivalry.user_a_id == user.id,
                                        Rivalry.user_b_id == user.id))
    ).scalar_one_or_none()

def card(user):
    if user is None or not user.wants_rival:
        return None
    row = mine(user)
    if row is None:
        return {"waiting": True}

    lo, hi = _window(row.week)
    yours = xp_between(user.id, lo, hi)

    if row.is_ghost:
        return {"waiting": False, "ghost": True, "yours": yours,
                "theirs": row.ghost_score, "opponent": None,
                "leading": yours > row.ghost_score, "row": row}

    other = row.user_b if row.user_a_id == user.id else row.user_a
    theirs = xp_between(other.id, lo, hi) if other else 0
    return {"waiting": False, "ghost": False, "yours": yours,
            "theirs": theirs, "opponent": other,
            "leading": yours > theirs, "row": row}

def pair(week=None):
    week = week or week_start()
    already = set(db.session.execute(
        db.select(Rivalry.user_a_id).where(Rivalry.week == week)).scalars())
    already |= set(x for x in db.session.execute(
        db.select(Rivalry.user_b_id).where(Rivalry.week == week)).scalars()
        if x)

    willing = [u for u in db.session.execute(
        db.select(User).where(User.wants_rival.is_(True),
                              User.is_suspended.is_(False),
                              User.username.isnot(None))).scalars()
        if u.id not in already]

    willing.sort(key=lambda u: (level_for_xp(u.xp_total or 0), u.id))
    random.Random(week.isoformat()).shuffle(willing)
    willing.sort(key=lambda u: level_for_xp(u.xp_total or 0))

    pairs = ghosts = 0
    i = 0
    while i + 1 < len(willing):
        a, b = willing[i], willing[i + 1]
        gap = abs(level_for_xp(a.xp_total or 0) - level_for_xp(b.xp_total or 0))
        if gap > LEVEL_WINDOW:
            # Too far apart to be a contest - ghost the lower one and move on.
            _ghost(a, week)
            ghosts += 1
            i += 1
            continue
        db.session.add(Rivalry(week=week, user_a_id=a.id, user_b_id=b.id))
        pairs += 1
        i += 2

    if i < len(willing):
        _ghost(willing[i], week)
        ghosts += 1

    db.session.commit()
    return pairs, ghosts

def _ghost(user, week):
    previous = week - timedelta(days=7)
    lo, hi = _window(previous)
    db.session.add(Rivalry(week=week, user_a_id=user.id, user_b_id=None,
                           ghost_score=xp_between(user.id, lo, hi)))


def settle(week=None):
    """Score and pay a finished week. Idempotent."""
    week = week or (week_start() - timedelta(days=7))
    lo, hi = _window(week)

    rows = db.session.execute(
        db.select(Rivalry).where(Rivalry.week == week,
                                 Rivalry.settled_at.is_(None))).scalars().all()

    from . import economy, notify
    for row in rows:
        row.score_a = xp_between(row.user_a_id, lo, hi)
        row.score_b = (row.ghost_score if row.is_ghost
                       else xp_between(row.user_b_id, lo, hi))
        row.settled_at = _utcnow()

        if row.is_ghost:
            if row.score_a > row.score_b:
                economy.earn(row.user_a, GHOST_WIN_COINS, "rival",
                             "%s:%d" % (week.isoformat(), row.id))
                notify.send_once(row.user_a, "rival", str(row.id),
                                 "You beat your own last week",
                                 "%d XP against %d." % (row.score_a,
                                                        row.score_b))
            continue

        for me, mine_, them in ((row.user_a, row.score_a, row.score_b),
                                (row.user_b, row.score_b, row.score_a)):
            if mine_ > them:
                economy.earn(me, WIN_COINS, "rival",
                             "%s:%d" % (week.isoformat(), row.id))
                title = "You won this week's rivalry"
            elif mine_ == them:
                economy.earn(me, DRAW_COINS, "rival",
                             "%s:%d" % (week.isoformat(), row.id))
                title = "Your rivalry ended level"
            else:
                title = "Your rival edged you out"
            notify.send_once(me, "rival", str(row.id), title,
                             "%d XP against %d." % (mine_, them))

    db.session.commit()
    return len(rows)


def register_cli(app):
    @app.cli.command("rivals-roll")
    def _roll():
        print("settled %d" % settle())
        pairs, ghosts = pair()
        print("paired %d, ghosted %d" % (pairs, ghosts))


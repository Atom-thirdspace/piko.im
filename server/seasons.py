from datetime import timedelta
from .models import Season, SeasonResult, User, XpEvent, _utcnow, db
from .progress import level_for_xp

LENGTH_DAYS = 28

TIERS = (
    (4000, "diamond", "Diamond"),
    (2000, "platinum", "Platinum"),
    (900,  "gold",     "Gold"),
    (300,  "silver",   "Silver"),
    (0,    "bronze",   "Bronze"),
)

def tier_for(score):
    for threshold, key, label in TIERS:
        if score >= threshold:
            return {"key": key, "label": label, "floor": threshold}
    return {"key": "bronze", "label": "Bronze", "floor": 0}


def next_tier(score):
    above = [t for t in reversed(TIERS) if t[0] > score]
    if not above:
        return None
    threshold, key, label = above[0]
    return {"key": key, "label": label, "needed": threshold - score}


def current():
    from .models import current_season
    return current_season()


def score_for(user, season):
        return int(db.session.execute(
        db.select(db.func.coalesce(db.func.sum(XpEvent.amount), 0))
        .where(XpEvent.user_id == user.id,
               XpEvent.created_at >= season.starts_at,
               XpEvent.created_at < season.ends_at)).scalar() or 0)


def ladder(season, limit=50):
    totals = (db.select(XpEvent.user_id.label("uid"),
                        db.func.sum(XpEvent.amount).label("xp"))
              .where(XpEvent.created_at >= season.starts_at,
                     XpEvent.created_at < season.ends_at)
              .group_by(XpEvent.user_id).subquery())

    rows = db.session.execute(
        db.select(User, totals.c.xp)
        .join(totals, totals.c.uid == User.id)
        .where(User.username.isnot(None),
               User.show_on_leaderboard.is_(True))
        .order_by(totals.c.xp.desc(), User.created_at.asc())
        .limit(limit)).all()

    return [{"rank": i, "user": u, "score": int(xp or 0),
             "tier": tier_for(int(xp or 0)), "level": level_for_xp(u.xp_total or 0)}
            for i, (u, xp) in enumerate(rows, 1)]

def card(user):
    season = current()
    if season is None or user is None:
        return None
    score = score_for(user, season)
    left = season.ends_at - _utcnow()
    return {
        "season": season,
        "score": score,
        "tier": tier_for(score),
        "next": next_tier(score),
        "days_left": max(0, left.days),
        "history": history(user, limit=3),
    }

def history(user, limit=6):
    rows = db.session.execute(
        db.select(SeasonResult, Season)
        .join(Season, Season.id == SeasonResult.season_id)
        .where(SeasonResult.user_id == user.id)
        .order_by(Season.starts_at.desc()).limit(limit)).all()
    return [{"season": s, "score": r.score, "rank": r.rank,
             "tier": tier_for(r.score)} for r, s in rows]

def open_next(name=None, starts_at=None):
    last = db.session.execute(
        db.select(Season).order_by(Season.ends_at.desc()).limit(1)
    ).scalar_one_or_none()

    starts = starts_at or (last.ends_at if last else _utcnow())
    ends = starts + timedelta(days=LENGTH_DAYS)
    slug = starts.strftime("s%Y%m%d")

    if db.session.execute(db.select(Season.id)
                          .filter_by(slug=slug)).scalar():
        return None

    row = Season(slug=slug, name=name or starts.strftime("Season of %B %Y"),
                 starts_at=starts, ends_at=ends)
    db.session.add(row)
    db.session.commit()
    return row

def close(season):
    if season.closed_at is not None:
        return 0

    standings = ladder(season, limit=1000)
    for place in standings:
        db.session.add(SeasonResult(
            season_id=season.id, user_id=place["user"].id,
            score=place["score"], rank=place["rank"],
            tier=place["tier"]["key"]))

    season.closed_at = _utcnow()
    db.session.commit()


    from . import economy, notify
    for place in standings:
        payout = {"diamond": 400, "platinum": 250, "gold": 150,
                  "silver": 80, "bronze": 30}[place["tier"]["key"]]
        economy.earn(place["user"], payout, "season", season.slug)
        notify.send_once(place["user"], "season", season.slug,
                         "%s finished" % season.name,
                         "You placed %d with %d XP - %s tier, %d coins."
                         % (place["rank"], place["score"],
                            place["tier"]["label"], payout),
                         url="/leaderboard/?scope=season")
    return len(standings)

def register_cli(app):
    import click

    @app.cli.command("season-open")
    @click.option("--name", default=None)
    def _open(name):
        row = open_next(name=name)
        print("created %s" % row.slug if row else "one already covers that window")

    @app.cli.command("season-roll")
    def _roll():
        due = db.session.execute(
            db.select(Season).where(Season.ends_at <= _utcnow(),
                                    Season.closed_at.is_(None))).scalars().all()
        for season in due:
            print("closed %s with %d placements" % (season.slug, close(season)))
        if current() is None:
            row = open_next()
            if row:
                print("opened %s" % row.slug)

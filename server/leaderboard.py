import time
from datetime import timedelta
from flask import Blueprint, jsonify, render_template, request
from .models import User, XpEvent, _utcnow, db
from .progress import level_for_xp
from .session import current_user

leaderboard_bp = Blueprint("leaderboard", __name__)

SCOPES = {"week": "This week", "all": "All time", "streak": "Streaks"}
BOARD_SIZE = 50
CACHE_TTL = 60         

_cache = {}

def _eligible():
     return (User.username.isnot(None), User.show_on_leaderboard.is_(True))

def _week_totals():
    since = _utcnow() - timedelta(days=7)
    return (db.select(XpEvent.user_id.label("uid"),
                      db.func.sum(XpEvent.amount).label("xp"))
            .where(XpEvent.created_at >= since)
            .group_by(XpEvent.user_id)
            .subquery())

def _row(rank, r, score):
    return {"rank": rank, "user_id": r.id, "username": r.username,
            "=name": r.name or r.username, "avatar_url": r.avatar_url,
            "score": int(score or 0), "streak": r.streak_days or 0,
            "level": level_for_xp(r.xp_total or 0)}

_COLUMNS = (User.id, User.username, User.name, User.avatar_url,
            User.xp_total, User.streak_days)

def _fetch(scope, limit):
    if scope == "week":
        earned = _week_totals()
        rows = db.session.execute(
            db.select(*_COLUMNS, earned.c.xp)
            .join(earned, earned.c.uid == User.id)
            .where(*_eligible())
            # created_at breaks ties the same way everywhere, so the order is
            # stable between two requests a second apart.
            .order_by(earned.c.xp.desc(), User.created_at.asc())
            .limit(limit)
        ).all()
        return [_row(i, r, r.xp) for i, r in enumerate(rows, 1)]

    if scope == "streak":
        rows = db.session.execute(
            db.select(*_COLUMNS).where(*_eligible(), User.streak_days > 0)
            .order_by(User.streak_days.desc(), User.xp_total.desc(),
                      User.created_at.asc())
            .limit(limit)
        ).all()
        return [_row(i, r, r.streak_days) for i, r in enumerate(rows, 1)]

    rows = db.session.execute( db.select(*_COLUMNS).where(*_eligible())
        .order_by(User.xp_total.desc(), User.created_at.asc())
        .limit(limit)).all()
    return [_row(i, r, r.xp_total) for i, r in enumerate(rows, 1)]


def board(scope, limit=BOARD_SIZE):
    now = time.monotonic()
    hit = _cache.get(scope)
    if hit and now - hit[0] < CACHE_TTL and len(hit[1]) >= min(limit, BOARD_SIZE):
        return hit[1][:limit]
    rows = _fetch(scope, limit)
    _cache[scope] = (now, rows)
    return rows

def standing(scope, user):
    if user is None or not user.username:
        return None
    if not user.show_on_leaderboard:
        return {"hidden" : True}
    
    if scope == "week":
        earned = _week_totals()
        score = db.session.execute(
            db.select(earned.c.xp).where(earned.c.uid == user.id)).scalar() or 0
        ahead = (db.select(db.func.count()).select_from(User)
                 .join(earned, earned.c.uid == User.id)
                 .where(*_eligible(), earned.c.xp > score))
    elif scope == "streak":
        score = user.streak_days or 0
        ahead = (db.select(db.func.count()).select_from(User)
                 .where(*_eligible(), User.streak_days > score))
    else:
        score = user.xp_total or 0
        ahead = (db.select(db.func.count()).select_from(User).where(
            *_eligible(),
            db.or_(User.xp_total > score,
                   db.and_(User.xp_total == score,
                           User.created_at < user.created_at))))

    return {"hidden": False, "rank": (db.session.execute(ahead).scalar() or 0) + 1,
            "score": int(score), "level": level_for_xp(user.xp_total or 0)}

def _scope():
    scope = request.args.get("scope", "week")
    return scope if scope in SCOPES else "week"


@leaderboard_bp.route("/leaderboard/")
def index():
    scope = _scope()
    return render_template("leaderboard.html", scope=scope, scopes=SCOPES,
                           rows=board(scope), you=standing(scope, current_user()),
                           viewer=current_user())


@leaderboard_bp.route("/api/leaderboard")
def api():
    scope = _scope()
    return jsonify(scope=scope, rows=board(scope),
                   you=standing(scope, current_user()))
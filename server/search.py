from flask import Blueprint, render_template, request

from .admin_gate import is_admin
from .content import visible
from .models import Lesson, Problem, Track, User, db
from .session import current_user

search_bp = Blueprint("search", __name__)

LIMIT = 10
MIN_CHARS = 2


def _term(q):
    """Drop LIKE metacharacters rather than escaping them.

    'zeb%ra' therefore searches for 'zebra' and '100%' for '100', which is
    the forgiving behaviour a search box wants. Stripping can empty the
    term, though, and an empty term would build the pattern '%%' - which
    matches every row - so the caller checks the length of what comes back,
    not of what was typed.
    """
    return q.replace("\\", "").replace("%", "").replace("_", "").strip()

@search_bp.route("/search")
def page():
    q = (request.args.get("q") or "").strip()
    user = current_user()
    results = {"problems": [], "lessons": [], "tracks": [], "people": []}
    term = _term(q)

    if len(term) >= MIN_CHARS:
        like = "%%%s%%" % term
        results["problems"] = db.session.execute(
            visible(db.select(Problem).where(
                db.or_(Problem.title.ilike(like), Problem.slug.ilike(like),
                       Problem.topic.ilike(like))), Problem, user)
            .order_by(Problem.title).limit(LIMIT)).scalars().all()

        results["lessons"] = db.session.execute(
            visible(db.select(Lesson).where(Lesson.title.ilike(like)),
                    Lesson, user).order_by(Lesson.title).limit(LIMIT)
        ).scalars().all()

        results["tracks"] = db.session.execute(
            visible(db.select(Track).where(Track.title.ilike(like)),
                    Track, user).order_by(Track.title).limit(LIMIT)
        ).scalars().all()

        people = db.select(User).where(
            db.or_(User.username.ilike(like), User.name.ilike(like)))
        if not (user and is_admin(user)):
            people = people.where(User.username.isnot(None))
        results["people"] = db.session.execute(
            people.order_by(User.username).limit(LIMIT)).scalars().all()

    total = sum(len(v) for v in results.values())
    short = bool(q) and len(term) < MIN_CHARS
    return render_template("search.html", q=q, results=results, total=total,
                           short=short)
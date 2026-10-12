from flask import Blueprint, jsonify, render_template, request

from . import contentcache
from .admin_gate import is_admin
from .content import visible
from .models import Lesson, Problem, Track, Unit, User, db
from .session import current_user

search_bp = Blueprint("search", __name__)

LIMIT = 10
MIN_CHARS = 2
CACHE_TTL = 45.0
KINDS = ("problem","lesson","track","person")
LABELS = {"problem": "Problems", "lesson": "Lessons",
          "track": "Courses", "person": "People"}



def _term(q):
    return q.replace("\\", "").replace("%", "").replace("_", "").strip()[:60]

def _branch(stmt):
    return db.select(stmt.limit(LIMIT).subquery())

def _statements(term, user):
    like = "%%%s%%" % term
    blank = db.literal("")

    problems = visible(
        db.select(
            db.literal("problem").label("kind"),
            Problem.id.label("id"),
            Problem.slug.label("slug"),
            Problem.title.label("title"),
            db.func.coalesce(Problem.topic, "").label("sub"),
            db.func.coalesce(Problem.difficulty, "").label("badge"),
            blank.label("track_slug"),
            blank.label("unit_slug"),
            Problem.status.label("status"),
        ).where(db.or_(Problem.title.ilike(like),
                       Problem.slug.ilike(like),
                       Problem.topic.ilike(like))),
        Problem, user)

    lessons = visible(
        db.select(
            db.literal("lesson"),
            Lesson.id,
            Lesson.slug,
            Lesson.title,
            db.func.concat(db.func.coalesce(Track.title, ""),
                           db.literal(" / "),
                           db.func.coalesce(Unit.title, "")),
            db.func.coalesce(Lesson.kind, ""),
            db.func.coalesce(Track.slug, ""),
            db.func.coalesce(Unit.slug, ""),
            Lesson.status,
        ).outerjoin(Unit, Lesson.unit_id == Unit.id)
         .outerjoin(Track, Unit.track_id == Track.id)
         .where(Lesson.title.ilike(like)),
        Lesson, user)

    tracks = visible(
        db.select(
            db.literal("track"), Track.id, Track.slug, Track.title,
            db.func.coalesce(Track.description, ""), blank, blank, blank,
            Track.status,
        ).where(Track.title.ilike(like)),
        Track, user)

    people = db.select(
        db.literal("person"), User.id,
        db.func.coalesce(User.username, ""),
        db.func.coalesce(User.name, User.username, ""),
        blank, blank, blank, blank, db.literal("published"),
    ).where(db.or_(User.username.ilike(like), User.name.ilike(like)))
    if not (user and is_admin(user)):
        people = people.where(User.username.isnot(None))

    return (problems, lessons, tracks, people)

def _query(term, user):
    rows = db.session.execute(
        db.union_all(*(_branch(s) for s in _statements(term, user)))
    ).mappings().all()

    grouped = {kind: [] for kind in KINDS}
    for row in rows:
        bucket = grouped.get(row["kind"])
        if bucket is not None and len(bucket) < LIMIT:
            bucket.append(dict(row))
    for bucket in grouped.values():
        bucket.sort(key=lambda r: r["title"].lower())
    return grouped


def results_for(term, user):
    if len(term) < MIN_CHARS:
        return {kind: [] for kind in KINDS}
    return contentcache.cached(
        "search:%s" % term.lower(),
        lambda: _query(term, user),
        ttl=CACHE_TTL,
        user=user,
    )

def _payload(q, user):
    term = _term(q)
    grouped = results_for(term,user)
    return {
        "q": q,
        "term": term,
        "short": bool(q) and len(term) < MIN_CHARS,
        "groups": grouped,
        "counts": {kind: len(rows) for kind, rows in grouped.items()},
        "total": sum(len(rows) for rows in grouped.values()),
    }

@search_bp.route("/search")
def page():
    data = _payload(request.args.get("q") or "", current_user())
    return render_template("search.html", labels=LABELS, kinds=KINDS, **data)

@search_bp.route("/api/search")
def api():
    return jsonify(_payload(request.args.get("q") or "", current_user()))

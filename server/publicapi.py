import hashlib
import json
import time
from collections import defaultdict, deque
from flask import Blueprint, jsonify, request

from .learning.catalog import TOPICS
from .learning.markdown import render as render_md
from .models import Lesson, Problem, Track, Unit, db

api_bp = Blueprint("publicapi",__name__, url_prefix="/api/v1")

VERSION = "1.0"
RATE_LIMIT = 120                 
RATE_WINDOW = 60                 
MAX_PER_PAGE = 100
DEFAULT_PER_PAGE = 25
CACHE_SECONDS = 300


_hits = defaultdict(deque)

def _client_ip():
    return request.remote_addr or "unknown"

def _rate_limited():
    now = time.monotonic()
    seen = _hits[_client_ip()]
    while seen and now - seen[0] > RATE_WINDOW:
        seen.popleft()
    if len(seen) >= RATE_LIMIT:
        return True
    seen.append(now)

    # Unbounded dict growth is the obvious leak; prune idle buckets.
    if len(_hits) > 4096:
        for ip in [k for k, v in _hits.items()
                   if not v or now - v[-1] > RATE_WINDOW]:
            _hits.pop(ip, None)
    return False

def _error(code, message, status):
    return jsonify(error={"code": code, "message": message}), status


def _ok(payload):
    body = json.dumps(payload, sort_keys=True, default=str)
    etag = '"%s"' % hashlib.blake2b(body.encode("utf-8"),
                                    digest_size=16).hexdigest()

    if request.headers.get("If-None-Match") == etag:
        resp = jsonify()
        resp.status_code = 304
    else:
        resp = jsonify(payload)

    resp.headers["ETag"] = etag
    resp.headers["Cache-Control"] = "public, max-age=%d" % CACHE_SECONDS
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    resp.headers["X-API-Version"] = VERSION
    return resp

@api_bp.before_request
def guard():
    if request.method == "OPTIONS":
        return None
    if _rate_limited():
        body, status = _error(
            "rate_limited",
            "Too many requests. The limit is %d per %d seconds."
            % (RATE_LIMIT, RATE_WINDOW), 429)
        body.headers["Retry-After"] = str(RATE_WINDOW)
        return body, status
    return None


@api_bp.errorhandler(404)
def _not_found(_exc):
    return _error("not_found", "No such resource.", 404)


def _page_args():
    try:
        page = max(int(request.args.get("page", 1)), 1)
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = int(request.args.get("per_page", DEFAULT_PER_PAGE))
    except (TypeError, ValueError):
        per_page = DEFAULT_PER_PAGE
    return page, min(max(per_page, 1), MAX_PER_PAGE)

def _paginate(stmt, page, per_page):
    total = db.session.execute(
        db.select(db.func.count()).select_from(stmt.subquery())).scalar() or 0
    rows = db.session.execute(
        stmt.limit(per_page).offset((page - 1) * per_page)).scalars().all()
    return rows, {"page": page, "per_page": per_page, "total": total,
                  "pages": max((total + per_page - 1) // per_page, 1)}


def _track_brief(t):
    return {"slug": t.slug, "title": t.title, "description": t.description,
            "position": t.position, "units": len(t.units)}

def _lesson_brief(l):
    return {"slug": l.slug, "title": l.title, "kind": l.kind, "xp": l.xp,
            "position": l.position,
            "problem": l.problem.slug if l.problem else None}


def _lesson_full(track, unit, lesson):
    from .learning.catalog import quiz_for

    out = _lesson_brief(lesson)
    out.update(track=track.slug, unit=unit.slug,
               body_md=lesson.body_md,
               body_html=str(render_md(lesson.body_md or "")))

    if lesson.kind == "quiz":
        # .public() is what omits the answer key; do not inline this.
        out["quiz"] = [q.public()
                       for q in quiz_for(track.slug, unit.slug, lesson.slug)]
    return out


def _unit_full(u):
    return {"slug": u.slug, "title": u.title, "level": u.level,
            "topic": u.topic, "position": u.position,
            "lessons": [_lesson_brief(l) for l in u.lessons]}


def _problem_brief(p):
    return {"slug": p.slug, "title": p.title, "topic": p.topic,
            "difficulty": p.difficulty, "xp": p.xp}


def _problem_full(p):
    samples = [t for t in p.tests if t.is_sample]
    return dict(_problem_brief(p),
                statement_md=p.statement_md,
                statement_html=str(render_md(p.statement_md or "")),
                time_limit_sec=p.time_limit_sec,
                memory_mb=p.memory_mb,
                total_tests=len(p.tests),     # the count, never the cases
                samples=[{"stdin": t.stdin,
                          "expected_stdout": t.expected_stdout}
                         for t in samples])

@api_bp.route("/")
def index():
    return _ok({
         "endpoints": {
            "topics": "/api/v1/topics",
            "tracks": "/api/v1/tracks",
            "track": "/api/v1/tracks/<track_slug>",
            "lesson": "/api/v1/tracks/<track_slug>/<unit_slug>/<lesson_slug>",
            "problems": "/api/v1/problems?topic=&difficulty=&q=&page=&per_page=",
            "problem": "/api/v1/problems/<problem_slug>",
        },
        "notes": "Read-only. Hidden tests, hints and quiz answers are never "
                 "served.",
    })

@api_bp.route("/topics")
def topics():
    return _ok({"items": [{"key": k, "title": t} for k, t in TOPICS]})

@api_bp.route("/tracks")
def tracks():
    rows = db.session.execute(
        db.select(Track).order_by(Track.position)).scalars().all()
    return _ok({"items": [_track_brief(t) for t in rows]})

@api_bp.route("/tracks/<track_slug>")
def track(track_slug):
    t = db.session.execute(
        db.select(Track).filter_by(slug=track_slug)).scalar_one_or_none()
    if t is None:
        return _error("not_found", "No track %r." % track_slug, 404)
    return _ok(dict(_track_brief(t), units=[_unit_full(u) for u in t.units]))


@api_bp.route("/tracks/<track_slug>/<unit_slug>/<lesson_slug>")
def lesson(track_slug, unit_slug, lesson_slug):
    row = db.session.execute(
        db.select(Track, Unit, Lesson)
        .join(Unit, Unit.track_id == Track.id)
        .join(Lesson, Lesson.unit_id == Unit.id)
        .where(Track.slug == track_slug, Unit.slug == unit_slug,
               Lesson.slug == lesson_slug)
    ).one_or_none()
    if row is None:
        return _error("not_found", "No such lesson.", 404)
    return _ok(_lesson_full(*row))


@api_bp.route("/problems")
def problems():
    page, per_page = _page_args()
    stmt = db.select(Problem).order_by(Problem.slug)

    topic = request.args.get("topic")
    if topic:
        stmt = stmt.where(Problem.topic == topic)
    difficulty = request.args.get("difficulty")
    if difficulty:
        stmt = stmt.where(Problem.difficulty == difficulty)
    q = (request.args.get("q") or "").strip()
    if q:
        like = "%%%s%%" % q.replace("%", "").replace("_", "")
        stmt = stmt.where(db.or_(Problem.title.ilike(like),
                                 Problem.slug.ilike(like)))

    rows, meta = _paginate(stmt, page, per_page)
    return _ok({"items": [_problem_brief(p) for p in rows], **meta})


@api_bp.route("/problems/<problem_slug>")
def problem(problem_slug):
    p = db.session.execute(
        db.select(Problem).filter_by(slug=problem_slug)).scalar_one_or_none()
    if p is None:
        return _error("not_found", "No problem %r." % problem_slug, 404)
    return _ok(_problem_full(p))


@api_bp.route("/health")
def health():
    try:
        db.session.execute(db.select(1))
        return _ok({"status": "ok", "version": VERSION})
    except Exception:
        return _error("unavailable", "Database Unreachable", 503)

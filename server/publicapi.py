import hashlib
import json
import time
from collections import defaultdict, deque
from functools import wraps

from flask import Blueprint, g, jsonify, request, url_for
from .apikeys import resolve, touch
from .judge import LANGUAGES as JUDGE_LANGUAGES, verdicts as V

from .learning.catalog import TOPICS
from .learning.markdown import render as render_md
from .models import (API_SCOPES, PUBLISHED, Enrollment, JudgeJob, Lesson,
                     Problem, Submission, Track, Unit, db,
                     may_read_editorial)

api_bp = Blueprint("publicapi",__name__, url_prefix="/api/v1")

VERSION = "1.0"
RATE_LIMIT = 120                 
RATE_WINDOW = 60                 
MAX_PER_PAGE = 100
DEFAULT_PER_PAGE = 25
CACHE_SECONDS = 300
TIER_ANON = 120
TIER_KEY = 600
TIER_PRO = 2000

MAX_SOURCE_BYTES = 64 * 1024


REQUIRE_KEY = False

_hits = defaultdict(deque)

def _client_ip():
    return request.remote_addr or "unknown"

def _bearer():
    header = request.headers.get("Authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return ""

def _json(payload, status=200):
    resp = jsonify(payload)
    resp.status_code = status
    resp.headers["Cache-Control"] = "private, no-store"
    resp.headers["X-API-Version"] = VERSION
    if getattr(g, "api_limit", None):
        resp.headers["X-RateLimit-Limit"] = str(g.api_limit)
    return resp


def _allows_any(*scopes):
    key = getattr(g, "api_key", None)
    return key is not None and any(key.allows(s) for s in scopes)


def _published_problem(slug):
    return db.session.execute(
        db.select(Problem).filter_by(slug=slug, status=PUBLISHED)
    ).scalar_one_or_none()


def _rate_limited(bucket, limit):
    now = time.monotonic()
    seen = _hits[bucket]
    while seen and now - seen[0] > RATE_WINDOW:
        seen.popleft()
    if len(seen) >= limit:
        return True
    seen.append(now)

    if len(_hits) > 4096:
        for key in [k for k, v in _hits.items()
                    if not v or now - v[-1] > RATE_WINDOW]:
            _hits.pop(key, None)
    return False

def _error(code, message, status):
    return jsonify(error={"code": code, "message": message}), status


def _ok(payload, private=False):
    body = json.dumps(payload, sort_keys=True, default=str)
    etag = '"%s"' % hashlib.blake2b(body.encode("utf-8"),
                                    digest_size=16).hexdigest()

    if request.headers.get("If-None-Match") == etag:
        resp = jsonify()
        resp.status_code = 304
    else:
        resp = jsonify(payload)

    resp.headers["ETag"] = etag
    if private:
        # Never let a proxy or CDN hold one developer's data and hand it to
        # the next caller. No CORS either: this is not browser-public data.
        resp.headers["Cache-Control"] = "private, no-store"
    else:
        resp.headers["Cache-Control"] = "public, max-age=%d" % CACHE_SECONDS
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    resp.headers["X-API-Version"] = VERSION
    if getattr(g, "api_limit", None):
        resp.headers["X-RateLimit-Limit"] = str(g.api_limit)
    return resp

@api_bp.before_request
def guard():
    if request.method == "OPTIONS":
        return None

    g.api_key = None
    g.api_user = None

    raw = _bearer()

    if raw:
        key = resolve(raw)
        if key is None:
            return _error("bad_token", "That API key is not valid.", 401)
        g.api_key = key
        g.api_user = key.user
        touch(key, request.remote_addr or "")

    if g.api_key is None and REQUIRE_KEY:
        return _error("no_token", "This endpoint needs an API key.", 401)

    if g.api_key is None:
        bucket, limit = "ip:" + _client_ip(), TIER_ANON
    else:
        from .billing.service import is_pro
        limit = TIER_PRO if is_pro(g.api_user) else TIER_KEY
        bucket = "key:%d" % g.api_key.id

    if _rate_limited(bucket, limit):
        body, status = _error(
            "rate_limited",
            "Too many requests. The limit is %d per %d seconds."
            % (limit, RATE_WINDOW), 429)
        body.headers["Retry-After"] = str(RATE_WINDOW)
        body.headers["X-RateLimit-Limit"] = str(limit)
        return body, status

    g.api_limit = limit
    return None

def require_scope(scope):
    def wrap(view):
        @wraps(view)
        def inner(*args, **kwargs):
            key = getattr(g, "api_key", None)
            if key is None:
                return _error("no_token",
                              "This endpoint needs an API key.", 401)
            if not key.allows(scope):
                return _error("missing_scope",
                              "This key does not carry %r." % scope, 403)
            return view(*args, **kwargs)
        return inner
    return wrap


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


def _visible_units(t):
    """t.units is an unfiltered relationship, so drafts ride along with it."""
    return [u for u in t.units if u.status == PUBLISHED]


def _visible_lessons(u):
    return [l for l in u.lessons if l.status == PUBLISHED]


def _track_brief(t):
    return {"slug": t.slug, "title": t.title, "description": t.description,
            "position": t.position, "units": len(_visible_units(t))}

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
            "lessons": [_lesson_brief(l) for l in _visible_lessons(u)]}


def _problem_brief(p):
    return {"slug": p.slug, "title": p.title, "topic": p.topic,
            "difficulty": p.difficulty, "xp": p.xp}


def _problem_full(p):
    samples = [t for t in p.tests if t.is_sample]
    out = dict(_problem_brief(p),
               statement_md=p.statement_md,
               statement_html=str(render_md(p.statement_md or "")),
               time_limit_sec=p.time_limit_sec,
               memory_mb=p.memory_mb,
               total_tests=len(p.tests),     # the count, never the cases
               has_editorial=bool(p.editorial_published and p.editorial_md),
               samples=[{"stdin": t.stdin,
                         "expected_stdout": t.expected_stdout}
                        for t in samples])

    # Same gate as the website: solved it, or Pro.
    if (getattr(g, "api_user", None) is not None
            and p.editorial_md and may_read_editorial(g.api_user, p)):
        out["editorial_md"] = p.editorial_md
    return out

def _sub_payload(problem, sub):
    ordered = list(problem.tests)
    rows = []
    for t in sub.test_results:
        row = {"index": t.position, "verdict": t.verdict,
               "label": V.LABELS.get(t.verdict, t.verdict),
               "time_ms": t.time_ms, "is_sample": t.is_sample}
        if t.is_sample and t.position < len(ordered):
            case = ordered[t.position]
            row.update(stdin=case.stdin, expected=case.expected_stdout,
                       actual=t.stdout)
        rows.append(row)

    pending = sub.verdict in (V.QUEUED, V.RUNNING)
    return {"submission_id": sub.id,
            "status": "pending" if pending else "done",
            "problem": problem.slug,
            "language": sub.language,
            "verdict": sub.verdict,
            "label": V.LABELS.get(sub.verdict, sub.verdict),
            "passed": sub.passed,
            "total": sub.total,
            "max_time_ms": sub.max_time_ms,
            "compile_output": sub.compile_output or "",
            "created_at": sub.created_at.isoformat() if sub.created_at else None,
            "tests": rows,
            "first_failure": next(
                (r for r in rows if r["verdict"] != V.AC), None)}

@api_bp.route("/")
def index():
    return _ok({
         "endpoints": {
            "topics": "/api/v1/topics",
            "languages": "/api/v1/languages",
            "tracks": "/api/v1/tracks",
            "track": "/api/v1/tracks/<track_slug>",
            "lesson": "/api/v1/tracks/<track_slug>/<unit_slug>/<lesson_slug>",
            "problems": "/api/v1/problems?topic=&difficulty=&q=&page=&per_page=",
            "problem": "/api/v1/problems/<problem_slug>",
            "potd" : "/api/v1/potd"
        },
        "me": {
            "profile": "/api/v1/me",
            "next": "/api/v1/me/next",
            "streak": "/api/v1/me/streak",
            "submissions": "/api/v1/me/submissions?verdict=&page=&per_page=",
            "submit": "POST /api/v1/submissions",
            "submission": "/api/v1/submissions/<id>",
        },
        "auth": {
            "scheme": "Authorization: Bearer piko_sk_...",
            "keys_at": "/settings/#api",
            "docs": "/developers/",
            "scopes": API_SCOPES,
            "rate_limits": {"anonymous": TIER_ANON, "key": TIER_KEY,
                            "pro": TIER_PRO, "window_seconds": RATE_WINDOW},
        },
        "notes": "Reads are open; writing needs a scoped key. Hidden tests, "
                 "hints, quiz answers and unpublished drafts are never served.",
    })

@api_bp.route("/topics")
def topics():
    return _ok({"items": [{"key": k, "title": t} for k, t in TOPICS]})

@api_bp.route("/languages")
def languages():
    return _ok({"items": [
        {"key": lang.key,
         "label": lang.label,
         "source_name": lang.source_name,
         "compiled": lang.compile_cmd is not None,
         "default_memory_mb": lang.default_memory_mb}
        for lang in JUDGE_LANGUAGES.values()]})

@api_bp.route("/tracks")
def tracks():
    rows = db.session.execute(
        db.select(Track).where(Track.status == PUBLISHED)
        .order_by(Track.position)).scalars().all()
    return _ok({"items": [_track_brief(t) for t in rows]})

@api_bp.route("/tracks/<track_slug>")
def track(track_slug):
    t = db.session.execute(
        db.select(Track).where(Track.slug == track_slug,
                               Track.status == PUBLISHED)).scalar_one_or_none()
    if t is None:
        return _error("not_found", "No track %r." % track_slug, 404)
    return _ok(dict(_track_brief(t),
                    units=[_unit_full(u) for u in _visible_units(t)]))


@api_bp.route("/tracks/<track_slug>/<unit_slug>/<lesson_slug>")
def lesson(track_slug, unit_slug, lesson_slug):
    row = db.session.execute(
        db.select(Track, Unit, Lesson)
        .join(Unit, Unit.track_id == Track.id)
        .join(Lesson, Lesson.unit_id == Unit.id)
        .where(Track.slug == track_slug, Unit.slug == unit_slug,
               Lesson.slug == lesson_slug,
               Track.status == PUBLISHED, Unit.status == PUBLISHED,
               Lesson.status == PUBLISHED)
    ).one_or_none()
    if row is None:
        return _error("not_found", "No such lesson.", 404)
    return _ok(_lesson_full(*row))


@api_bp.route("/problems")
def problems():
    page, per_page = _page_args()
    stmt = (db.select(Problem).where(Problem.status == PUBLISHED)
            .order_by(Problem.slug))

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
        db.select(Problem).filter_by(slug=problem_slug, status=PUBLISHED)
    ).scalar_one_or_none()
    if p is None:
        return _error("not_found", "No problem %r." % problem_slug, 404)
    body = _problem_full(p)
    # The body varies by caller once an editorial is in it, so it must not
    # land in a shared cache.
    return _ok(body, private="editorial_md" in body)


@api_bp.route("/health")
def health():
    try:
        db.session.execute(db.select(1))
        return _ok({"status": "ok", "version": VERSION})
    except Exception:
        return _error("unavailable", "Database Unreachable", 503)


# --------------------------------------------------------------------------- #
# the caller's own data. Keyed, scoped, and never cached.
# --------------------------------------------------------------------------- #

@api_bp.route("/me")
@require_scope("me:read")
def me():
    from .billing.service import is_pro

    u = g.api_user
    return _ok({
        "id": u.id,
        "username": u.username,
        "xp_total": u.xp_total,
        "streak_days": u.streak_days,
        "streak_best": u.streak_best,
        "pro": is_pro(u),
        "joined": u.created_at,
        "key": {"name": g.api_key.name, "scopes": g.api_key.scopes},
    }, private=True)


@api_bp.route("/me/submissions")
@require_scope("submissions:read")
def my_submissions():
    page, per_page = _page_args()
    stmt = (db.select(Submission)
            .where(Submission.user_id == g.api_user.id)
            .order_by(Submission.created_at.desc()))

    verdict = request.args.get("verdict")
    if verdict:
        stmt = stmt.where(Submission.verdict == verdict)

    rows, meta = _paginate(stmt, page, per_page)
    return _ok({"items": [{
        "id": s.id,
        "problem": s.problem.slug if s.problem else None,
        "language": s.language,
        "verdict": s.verdict,
        "passed": s.passed,
        "total": s.total,
        "max_time_ms": s.max_time_ms,
        "created_at": s.created_at,
        # Their own source, so theirs to read back - but it does mean a
        # leaked key exposes their solutions.
        "source": s.source,
    } for s in rows], **meta}, private=True)


@api_bp.route("/submissions", methods=["POST"])
@require_scope("submissions:write")

def create_submission():
    from .billing.service import is_pro
    from .problems import _cached, _sha, _tests_fingerprint
    from .ratelimit import submit_block_reason

    user = g.api_user
    payload = request.get_json(silent=True) or {}
    slug = (payload.get("problem") or "").strip()
    language = payload.get("language") or ""
    source = payload.get("source") or ""

    problem = _published_problem(slug)
    if problem is None:
        return _error("not_found", "No problem %r." % slug, 404)
    if language not in JUDGE_LANGUAGES:
        return _error("bad_language",
                      "Unsupported language %r. See /api/v1/languages."
                      % language, 400)
    if not source.strip():
        return _error("empty_source", "There is no source to judge.", 400)
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        return _error("too_large", "Submissions cap at %d KB."
                      % (MAX_SOURCE_BYTES // 1024), 413)
    if not problem.tests:
        return _error("no_tests", "That problem has no test cases yet.", 503)

    blocked = submit_block_reason(user)
    if blocked:
        body, status = _error("submit_limited", blocked, 429)
        body.headers["Retry-After"] = "60"
        return body, status

    source_hash = _sha(source)
    tests_hash = _tests_fingerprint(problem)

    hit = _cached(user, problem, language, source_hash, tests_hash)
    if hit is not None:
        return _json(dict(_sub_payload(problem, hit), cached=True))

    sub = Submission(
        user_id=user.id, problem_id=problem.id, language=language,
        source=source, verdict=V.QUEUED, passed=0,
        total=len(problem.tests), max_time_ms=0,
        source_hash=source_hash, tests_hash=tests_hash)
    db.session.add(sub)
    db.session.flush()
    db.session.add(JudgeJob(submission_id=sub.id,
                            priority=1 if is_pro(user) else 0))
    db.session.commit()

    return _json(dict(_sub_payload(problem, sub), cached=False), 202)

@api_bp.route("/submissions/<int:sub_id>")
def submission(sub_id):
    if not _allows_any("submissions:read", "submissions:write"):
        return _error("missing_scope", "This needs 'submissions:read' or 'submissions:write'.", 403)
    sub = db.session.get(Submission, sub_id)
    if sub is None or sub.user_id != g.api_user.id:
        return _error("not_found", "No submission %d." % sub_id, 404)
    problem = db.session.get(Problem, sub.problem_id)
    if problem is None:
        return _error("not_found", "That problem has been removed.", 404)
    return _json(_sub_payload(problem, sub))

@api_bp.route("/me/next")
@require_scope("me:read")
def next_up():
    from . import recommend
    user = g.api_user
    enrollment = db.session.execute(
        db.select(Enrollment).where(Enrollment.user_id == user.id,
                                    Enrollment.is_primary.is_(True))).scalar_one_or_none()

    lesson_out = None
    if enrollment is not None and enrollment.current_lesson is not None:
        row = enrollment.current_lesson
        unit = row.unit
        if unit is not None:
            lesson_out = {
                "track": enrollment.track.slug,
                "unit": unit.slug,
                "slug": row.slug,
                "title": row.title,
                "kind": row.kind,
                "xp": row.xp,
                "problem": row.problem.slug if row.problem else None,
                "url": url_for("learn.lesson", track_slug=enrollment.track.slug,
                               unit_slug=unit.slug, lesson_slug=row.slug,
                               _external=True),
            }

    pick = recommend.next_problem(user)
    return _json({
        "lesson": lesson_out,
        "problem": _problem_brief(pick["problem"]) if pick else None,
        "reason": pick["reason"] if pick else None,
    })

@api_bp.route("/me/streak")
@require_scope("me:read")
def my_streak():
    from .activity import heatmap
    from .progress import streak_state, user_today

    user = g.api_user
    today = user_today(user)
    today_xp = heatmap(user).get("today_xp", 0)
    goal = user.daily_goal_xp or 0
    return _json({
        "day": today.isoformat(),
        "streak_days": user.streak_days or 0,
        "streak_best": user.streak_best or 0,
        "today_xp": today_xp,
        "goal_xp": goal,
        "remaining_xp": max(goal - today_xp, 0),
        "state": streak_state(user, today),
    })

@api_bp.route("/potd")
def problem_of_the_day():
    from . import potd as potd_mod

    card = potd_mod.card(g.api_user)
    if card is None:
        return _error("not_found", "No problem of the day yet.", 404)
    body = {"day": card["day"].isoformat(),
            "bonus": card["bonus"],
            "solvers": card.get("solvers", 0),
            "solved": card["solved"],
            "problem": _problem_brief(card["problem"])}

    return _json(body) if g.api_user is not None else _ok(body)

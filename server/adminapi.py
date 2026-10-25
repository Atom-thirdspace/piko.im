from datetime import timedelta
from flask import g, request
from . import adminstats, csrf
from .admin_gate import is_admin
from .models import AdminAction, ApiKey, Problem, Submission, User, _utcnow, db
from .publicapi import _error, _json, _page_args, _paginate, api_bp

ELEVATION_TTL = timedelta(minutes=15)

def _audit(action, target="", detail=""):
    db.session.add(AdminAction(admin_id=g.api_user.id, action=action,
                               target=str(target)[:120], detail=detail[:500]))
    db.session.commit()

def admin_read(view):
    from functools import wraps

    @wraps(view)
    def inner(*args, **kwargs):
        key = getattr(g, "api_key", None)
        if key is None or not key.allows("admin:read"):
            # 404, not 403: an endpoint nobody should know exists.
            return _error("not_found", "No such resource.", 404)
        if not is_admin(g.api_user):
            return _error("not_found", "No such resource.", 404)
        return view(*args, **kwargs)
    return inner

def admin_write(view):
    from functools import wraps
    def inner(*args, **kwargs):
        key = getattr(g, "api_key", None)
        if key is None or not key.allows("admin:write"):
            return _error("not_found", "No such resource.", 404)
        if not is_admin(g.api_user):
            return _error("not_found", "No such resource.", 404)
        until = key.admin_elevated_until
        if until is None or until <= _utcnow():
            return _error("needs_unlock",
                          "This needs an admin unlock. "
                          "Run `piko admin unlock`.", 401)
        return view(*args, **kwargs)
    return inner


@api_bp.route("/admin/unlock", methods=["POST"])
@csrf.exempt
def admin_unlock_start():
    from .admin_code import send_code

    key = getattr(g, "api_key", None)
    if key is None or not key.allows("admin:write") or not is_admin(g.api_user):
        return _error("not_found", "No such resource.", 404)

    ok, message = send_code(g.api_user)
    _audit("adminapi.unlock_requested", g.api_user.email, message)
    return _json({"sent": ok, "message": message}, 200 if ok else 429)


@api_bp.route("/admin/unlock/verify", methods=["POST"])
@csrf.exempt
def admin_unlock_verify():
    from .admin_code import verify_code

    key = getattr(g, "api_key", None)
    if key is None or not key.allows("admin:write") or not is_admin(g.api_user):
        return _error("not_found", "No such resource.", 404)

    code = (request.get_json(silent=True) or {}).get("code", "")
    if not verify_code(g.api_user, code):
        _audit("adminapi.unlock_failed", g.api_user.email,
               request.remote_addr or "")
        return _error("bad_code", "That code is not right, or has expired.",
                      401)

    key.admin_elevated_until = _utcnow() + ELEVATION_TTL
    db.session.commit()
    _audit("adminapi.unlock", g.api_user.email, request.remote_addr or "")
    return _json({"elevated_until": key.admin_elevated_until,
                  "minutes": int(ELEVATION_TTL.total_seconds() // 60)})

@api_bp.route("/admin/lock", methods=["POST"])
@csrf.exempt
@admin_read
def admin_lock():
    key = g.api_key
    key.admin_elevated_until = None
    db.session.commit()
    _audit("adminapi.lock")
    return _json({"elevated": False})


@api_bp.route("/admin/stats")
@admin_read
def admin_stats():
    return _json({
        "headline": adminstats.headline(),
        "funnel": adminstats.funnel(),
        "content": adminstats.content_pipeline(),
        "judge": adminstats.judge_health(),
        "engagement": adminstats.engagement(),
        "verdicts": adminstats.verdict_mix(),
    })

@api_bp.route("/admin/traffic")
@admin_read
def admin_traffic():
    from . import traffic as traffic_mod

    try:
        days = min(max(int(request.args.get("days", 7)), 1), 90)
    except (TypeError, ValueError):
        days = 7
    try:
        top = min(max(int(request.args.get("top", 15)), 1), 50)
    except (TypeError, ValueError):
        top = 15

    buffered, dropped = traffic_mod.buffered()
    body = adminstats.traffic(days=days, top=top)
    body["buffer"] = {"pending": buffered, "dropped": dropped}
    return _json(body)

@api_bp.route("/admin/health")
@admin_read
def admin_health():
    from .health import _db_probe, judge_state, schema_drift

    probe = _db_probe()
    return _json({
        "db": probe,
        "schema": schema_drift() if probe["ok"] else {"ok": False},

    })

@api_bp.route("/admin/users")
@admin_read
def admin_users():
    page, per_page = _page_args()
    stmt = db.select(User).order_by(User.created_at.desc())

    query = (request.args.get("q") or "").strip()
    if query:
        like = "%%%s%%" % query.lower()
        stmt = stmt.where(db.or_(db.func.lower(User.username).like(like),
                                 db.func.lower(User.email).like(like),
                                 db.func.lower(User.name).like(like)))

    rows, meta = _paginate(stmt, page, per_page)
    return _json(dict(meta, items=[{
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "verified": u.email_verified_at is not None,
        "xp_total": u.xp_total,
        "streak_days": u.streak_days,
        "suspended": bool(u.is_suspended),
        "last_active": u.last_active_date,
        "joined": u.created_at,
    } for u in rows]))


@api_bp.route("/admin/audit")
@admin_read
def admin_audit():
    page, per_page = _page_args()
    stmt = db.select(AdminAction).order_by(AdminAction.created_at.desc())
    rows, meta = _paginate(stmt, page, per_page)
    return _json(dict(meta, items=[{
        "id": a.id, "action": a.action, "target": a.target,
        "detail": a.detail, "at": a.created_at,
        "admin": a.admin.username if a.admin else None} for a in rows]))

@api_bp.route("/admin/submissions/<int:sub_id>/rejudge", methods=["POST"])
@csrf.exempt
@admin_write
def admin_rejudge(sub_id):
    from .models import JudgeJob, judge_is_live
    from .judge import verdicts as V

    sub = db.session.get(Submission, sub_id)
    if sub is None:
        return _error("not_found", "No submission %d." % sub_id, 404)
    if not judge_is_live():
        return _error("judge_offline", "The judge is offline.", 503)

    sub.verdict = V.QUEUED
    sub.passed = 0
    db.session.add(JudgeJob(submission_id=sub.id, priority=2))
    db.session.commit()
    _audit("adminapi.rejudge", sub_id)
    return _json({"submission_id": sub.id, "status": "queued"})

@api_bp.route("/admin/users/<int:user_id>/xp", methods=["POST"])
@csrf.exempt
@admin_write
def admin_grant_xp(user_id):
    from .progress import award_xp

    user = db.session.get(User, user_id)
    if user is None:
        return _error("not_found", "No user %d." % user_id, 404)

    payload = request.get_json(silent=True) or {}
    try:
        amount = int(payload.get("amount", 0))
    except (TypeError, ValueError):
        return _error("bad_request", "amount must be a whole number.", 400)
    if not -10000 <= amount <= 10000 or amount == 0:
        return _error("bad_request", "amount must be non-zero and within "
                                     "10000.", 400)

    reason = (payload.get("reason") or "admin grant")[:64]
    award_xp(user, amount, reason, "adminapi")
    _audit("adminapi.grant_xp", user_id, "%+d %s" % (amount, reason))
    return _json({"user_id": user.id, "xp_total": user.xp_total})

@api_bp.route("/admin/problems/<slug>/publish", methods=["POST"])
@csrf.exempt
@admin_write
def admin_publish(slug):
    from .models import PUBLISHED

    problem = db.session.execute(
        db.select(Problem).filter_by(slug=slug)).scalar_one_or_none()
    if problem is None:
        return _error("not_found", "No problem %r." % slug, 404)
    if not problem.tests:
        return _error("no_tests", "That problem has no test cases.", 400)

    problem.status = PUBLISHED
    db.session.commit()
    _audit("adminapi.publish", slug)
    return _json({"slug": slug, "status": problem.status})



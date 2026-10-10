from flask import (Blueprint, abort, flash, jsonify, redirect,
                   render_template, request, url_for)

from ..learning.markdown import render as render_md
from ..models import Boss, BossRun, active_boss_run, db
from ..session import current_user, login_required
from . import engine, rules

arena_bp = Blueprint("arena", __name__, url_prefix="/arena")

def _boss_or_404(slug):
    row = db.session.execute(
        db.select(Boss).filter_by(slug=slug, is_live=True)).scalar_one_or_none()
    if row is None:
        abort(404)
    return row

def _run_or_404(run_id):
    row = db.session.get(BossRun, run_id)
    if row is None or row.user_id != current_user().id:
        abort(404)
    return row

@arena_bp.route("/")
@login_required
def index():
    user = current_user()
    engine.expire_stale()
    bosses = db.session.execute(
        db.select(Boss).where(Boss.is_live.is_(True))
        .order_by(Boss.tier, Boss.position, Boss.id)).scalars().all()
    recent = db.session.execute(
        db.select(BossRun).where(BossRun.user_id == user.id,
                                 BossRun.status != "active")
        .order_by(BossRun.started_at.desc()).limit(8)).scalars().all()
    return render_template("arena/index.html", bosses=bosses, recent=recent,
                           active=active_boss_run(user),
                           paid_left=max(0, rules.PAID_RUNS_PER_DAY
                                         - engine._paid_today(user)))

@arena_bp.route("/<slug>/start", methods=["POST"])
@login_required
def start(slug):
    boss = _boss_or_404(slug)
    run, error = engine.start(current_user(), boss,
                              stake=request.form.get("stake", "safe"))
    if error:
        flash(error, "error")
        return redirect(url_for("arena.index"))
    return redirect(url_for("arena.fight", run_id=run.id))

@arena_bp.route("/run/<int:run_id>/")
@login_required
def fight(run_id):
    run = _run_or_404(run_id)
    if run.status != "active":
        return redirect(url_for("arena.result", run_id=run.id))
    return render_template("arena/fight.html", run=run, boss=run.boss,
                           state=engine.state(run))

@arena_bp.route("/run/<int:run_id>/question")
@login_required
def question(run_id):
    run = _run_or_404(run_id)
    if run.status != "active":
        return jsonify(done=True, **engine.state(run))
    row = engine.serve(run)
    if row is None:
        engine.finish(run, "draw")
        return jsonify(done=True, **engine.state(run))
    return jsonify(done=False, question=engine.as_payload(run, row),
                   **engine.state(run))


@arena_bp.route("/run/<int:run_id>/answer", methods=["POST"])
@login_required
def answer(run_id):
    run = _run_or_404(run_id)
    if run.status != "active":
        return jsonify(done=True, **engine.state(run))

    payload = request.get_json(silent=True) or {}
    result = engine.answer(run, payload.get("question_id"),
                           payload.get("answer"), payload.get("choice"))
    if result.get("explain"):
        result["explain_html"] = str(render_md(result.pop("explain")))
    else:
        result.pop("explain", None)
    result["done"] = run.status != "active"
    return jsonify(**result)

@arena_bp.route("/run/<int:run_id>/forfeit", methods=["POST"])
@login_required
def forfeit(run_id):
    engine.forfeit(_run_or_404(run_id))
    return redirect(url_for("arena.result", run_id=run_id))

@arena_bp.route("/run/<int:run_id>/result")
@login_required
def result(run_id):
    from .. import economy
    run = _run_or_404(run_id)
    if run.status == "active":
        return redirect(url_for("arena.fight", run_id=run.id))
    return render_template("arena/result.html", run=run, boss=run.boss,
                           retry_cost=economy.ARENA_RETRY_COST,
                           coins=economy.balance(current_user()))

@arena_bp.route("/endless/start", methods=["POST"])
@login_required
def endless_start():
    boss = _boss_or_404(request.form.get("slug") or "big-o-wyrm")
    run, error = engine.start(current_user(), boss, mode="endless",
                              stake=request.form.get("stake", "safe"))
    if error:
        flash(error, "error")
        return redirect(url_for("arena.index"))
    return redirect(url_for("arena.fight", run_id=run.id))


@arena_bp.route("/endless/")
@login_required
def endless_board():
    return render_template("arena/endless.html", rows=engine.endless_board())


@arena_bp.route("/run/<int:run_id>/retry", methods=["POST"])
@login_required
def retry(run_id):
    ok, message = engine.retry(_run_or_404(run_id))
    flash(message, "success" if ok else "error")
    if ok:
        return redirect(url_for("arena.fight", run_id=run_id))
    return redirect(url_for("arena.result", run_id=run_id))

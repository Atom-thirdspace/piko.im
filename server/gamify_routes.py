from flask import (Blueprint, abort, flash, jsonify, redirect,
                   render_template, request, url_for)

from . import cosmetics, economy, mastery, speedrun
from .models import Problem, db
from .session import current_user, login_required

gamify_bp = Blueprint("gamify", __name__)

@gamify_bp.route("/wardrobe/")
@login_required
def wardrobe():
    user = current_user()
    return render_template("wardrobe.html", slots=cosmetics.SLOTS,
                           wardrobe=cosmetics.wardrobe(user),
                           coins=economy.balance(user))

@gamify_bp.route("/wardrobe/buy/<key>", methods=["POST"])
@login_required
def buy(key):
    ok, message = cosmetics.buy(current_user(), key)
    flash(message, "success" if ok else "error")
    return redirect(url_for("gamify.wardrobe"))


@gamify_bp.route("/wardrobe/equip/<slot>/<key>", methods=["POST"])
@login_required
def equip(slot, key):
    ok, message = cosmetics.equip(current_user(), slot, key)
    flash(message, "success" if ok else "error")
    return redirect(url_for("gamify.wardrobe"))


@gamify_bp.route("/coins/")
@login_required
def coins():
    user = current_user()
    return render_template("coins.html", balance=economy.balance(user),
                           rows=economy.recent(user, limit=40),
                           labels=economy.LABELS)


@gamify_bp.route("/mastery/")
@login_required
def mastery_page():
    user = current_user()
    return render_template("mastery.html", rows=mastery.for_user(user),
                           rusty=mastery.rusty(user),
                           half_life=int(mastery.HALF_LIFE_DAYS))


@gamify_bp.route("/problems/<slug>/speedrun", methods=["POST"])
@login_required
def speedrun_start(slug):
    problem = db.session.execute(
        db.select(Problem).filter_by(slug=slug)).scalar_one_or_none()
    if problem is None:
        abort(404)
    attempt, error = speedrun.start(current_user(), problem)
    if error:
        return jsonify(error=error), 400
    return jsonify(attempt_id=attempt.id,
                   started_at=attempt.started_at.isoformat())

@gamify_bp.route("/problems/<slug>/times/")
@login_required
def times(slug):
    problem = db.session.execute(
        db.select(Problem).filter_by(slug=slug)).scalar_one_or_none()
    if problem is None:
        abort(404)
    return render_template("speed_board.html", problem=problem,
                           rows=speedrun.leaderboard(problem),
                           mine=speedrun.best(current_user(), problem))


@gamify_bp.route("/records/")
@login_required
def records():
    return render_template("records.html",
                           rows=speedrun.mine(current_user(), limit=50))
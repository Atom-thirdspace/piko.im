from datetime import timedelta
from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

from .admin_gate import is_admin
from .learning.markdown import render as render_md
from .models import (Contest, ContestEntry, ContestProblem, Problem,
                     Submission, User, _utcnow, db)
from .session import current_user, login_required

contests_bp = Blueprint("contests", __name__, url_prefix="/contests")

PENALTY_MINUTES = 20

def phase(contest, now=None):
    now = now or _utcnow()
    if now < contest.starts_at:
        return "upcoming"
    if now < contest.ends_at:
        return "running"
    return "ended"

def entered(contest, user):
    if user is None:
        return False
    return db.session.execute(
        db.select(ContestEntry.id).filter_by(contest_id=contest.id,
                                             user_id=user.id)).scalar() is not None

def unlocked_problem_ids(user):
        if user is None:
             return set()
        now = _utcnow()
        return set(db.session.execute(
            db.select(ContestProblem.problem_id)
            .join(Contest, Contest.id == ContestProblem.contest_id)
            .join(ContestEntry, db.and_(ContestEntry.contest_id == Contest.id,
                                    ContestEntry.user_id == user.id))
            .where(Contest.published.is_(True),
                  Contest.starts_at <= now, Contest.ends_at > now)
        ).scalars())

def _freeze_at(contest):
         return contest.ends_at - timedelta(minutes=contest.freeze_minutes or 0)


def scoreboard(contest, viewer=None):
    pids = [cp.problem_id for cp in contest.problems]
    entrants = {e.user_id: e for e in contest.entries}
    if not pids or not entrants:
        return {"rows": [], "frozen": False, "letters": {}}

    cutoff = contest.ends_at
    frozen = False
    if phase(contest) == "running" and not (viewer and is_admin(viewer)):
        freeze = _freeze_at(contest)
        if _utcnow() >= freeze:
            cutoff, frozen = freeze, True

    subs = db.session.execute(
        db.select(Submission.user_id, Submission.problem_id,
                  Submission.verdict, Submission.created_at)
        .where(Submission.problem_id.in_(pids),
               Submission.user_id.in_(list(entrants)),
               Submission.created_at >= contest.starts_at,
               Submission.created_at < cutoff)
        .order_by(Submission.created_at)).all()

    cells = {}
    for row in subs:
        key = (row.user_id, row.problem_id)
        cell = cells.setdefault(key, {"tries": 0, "at": None})
        if cell["at"] is not None:
            continue                      
        if row.verdict == "accepted":
            delta = row.created_at - contest.starts_at
            cell["at"] = max(0, int(delta.total_seconds() // 60))
        else:
            cell["tries"] += 1

    users = {u.id: u for u in db.session.execute(
        db.select(User).where(User.id.in_(list(entrants)))).scalars()}

    rows = []
    for uid in entrants:
        solved, penalty, per_problem = 0, 0, {}
        for pid in pids:
            cell = cells.get((uid, pid))
            if cell is None:
                per_problem[pid] = None
                continue
            if cell["at"] is None:
                per_problem[pid] = {"solved": False, "tries": cell["tries"]}
                continue
            solved += 1
            penalty += cell["at"] + PENALTY_MINUTES * cell["tries"]
            per_problem[pid] = {"solved": True, "tries": cell["tries"],
                                "at": cell["at"]}
        rows.append({"user": users.get(uid), "solved": solved,
                     "penalty": penalty, "cells": per_problem})

    rows.sort(key=lambda r: (-r["solved"], r["penalty"],
                             (r["user"].username or "") if r["user"] else ""))
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    return {"rows": rows, "frozen": frozen,
            "letters": {cp.problem_id: cp.letter for cp in contest.problems}}

def _visible_contests(user):
    stmt = db.select(Contest).order_by(Contest.starts_at.desc())
    if user is None or not is_admin(user):
        stmt = stmt.where(Contest.published.is_(True))
    return db.session.execute(stmt).scalars().all()

def _contest_or_404(contest_id):
    contest = db.session.execute(
        db.select(Contest).filter_by(slug=slug)).scalar_one_or_none()
    if contest is None:
        abort(404)
    user = current_user()
    if not contest.published and not (user and is_admin(user)):
        abort(404)
    return contest

@contests_bp.route("/")
def index():
    rows = _visible_contests(current_user())
    buckets = {"running": [], "upcoming": [], "over": []}
    for c in rows:
        buckets[phase(c)].append(c)
    buckets["upcoming"].reverse()
    return render_template("contests/index.html", buckets=buckets)


@contests_bp.route("/<slug>/")
def detail(slug):
    contest = _contest_or_404(slug)
    user = current_user()
    state = phase(contest)
    joined = entered(contest, user)
    show = state != "upcoming" or (user is not None and is_admin(user))
    return render_template("contests/detail.html", contest=contest,
                           phase=state, joined=joined, show_problems=show,
                           body=render_md(contest.description_md),
                           entries=len(contest.entries))

@contests_bp.route("/<slug>/join", methods=["POST"])
@login_required
def join(slug):
    contest = _contest_or_404(slug)
    if phase(contest) == "over":
        flash("That contest has finished.", "error")
        return redirect(url_for("contests.detail", slug=slug))
    user = current_user()
    if not entered(contest, user):
        db.session.add(ContestEntry(contest_id=contest.id, user_id=user.id))
        try:
            db.session.commit()
        except Exception:                 # two tabs
            db.session.rollback()
    flash("You're in.", "success")
    return redirect(url_for("contests.detail", slug=slug))

@contests_bp.route("/<slug>/scoreboard")
def board(slug):
    contest = _contest_or_404(slug)
    return render_template("contests/scoreboard.html", contest=contest,
                           phase=phase(contest),
                           board=scoreboard(contest, current_user()))


    
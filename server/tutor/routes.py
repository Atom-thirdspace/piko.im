from datetime import timedelta

from flask import Blueprint, jsonify, request

from ..learning.markdown import render as render_md
from ..models import (Lesson, Problem, Submission, _utcnow, db,
                      log_tutor_message, tutor_calls_since)
from ..session import current_user, login_required
from . import guard
from .client import TutorError, ask, is_configured
from .prompt import build

tutor_bp = Blueprint("tutor", __name__, url_prefix="/api/tutor")


def _solved(user, problem_id):
    if not problem_id:
        return False
    return db.session.execute(
        db.select(Submission.id).filter_by(
            user_id=user.id, problem_id=problem_id, verdict="accepted"
        ).limit(1)
    ).scalar_one_or_none() is not None


@tutor_bp.route("/ask", methods=["POST"])
@login_required
def tutor_ask():
    user = current_user()
    if not is_configured():
        return jsonify(error="The tutor isn't switched on yet."), 503

    payload = request.get_json(silent=True) or {}
    question = guard.clean_question(payload.get("question"))

    problem = lesson = None
    if payload.get("lesson_id"):
        lesson = db.session.get(Lesson, payload["lesson_id"])
    if payload.get("problem_id"):
        problem = db.session.get(Problem, payload["problem_id"])
    if lesson is not None and problem is None and lesson.problem_id:
        problem = lesson.problem

    if lesson is None and problem is None:
        return jsonify(error="Open a lesson or problem first."), 400

    error, status = guard.check(user, question)
    if error:
        return jsonify(error=error), status

    # The mode is decided by the server from real progress, never by the client.
    if problem is not None:
        mode = "review" if _solved(user, problem.id) else "hint"
    else:
        mode = "explain"

    flagged = guard.looks_suspicious(question)
    system, user_prompt = build(mode, lesson=lesson, problem=problem,
                                question=question)

    try:
        answer, model = ask(system, user_prompt)
    except TutorError as exc:
        log_tutor_message(user, lesson, problem, mode, question, str(exc),
                          model="", ok=False, flagged=flagged)
        return jsonify(error=str(exc)), 502

    log_tutor_message(user, lesson, problem, mode, question, answer, model,
                      ok=True, flagged=flagged)

    used = tutor_calls_since(user, _utcnow() - timedelta(hours=1))
    return jsonify(
        mode=mode,
        answer_html=render_md(answer),
        remaining=max(0, guard.hourly_limit() - used),
    )
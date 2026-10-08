from datetime import timedelta

from flask import Blueprint, jsonify, request, abort

from ..learning.markdown import render as render_md
from ..models import (PUBLISHED, Lesson, Problem, Submission, _utcnow, db,
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
        if problem is not None and problem.status != PUBLISHED:
            problem = None
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
        remaining=max(0, guard.hourly_limit(user) - used),
    )

@tutor_bp.route("/explain", methods=["POST"])
@login_required
def tutor_explain():
    from ..billing.service import is_pro
    from ..judge import verdicts as V

    user = current_user()
    if not is_configured():
        return jsonify(error="The tutor isn't switched on yet."), 503
    if not is_pro(user):
        return jsonify(error="Diagnosing a failed submission is a Pro feature.",
                       upgrade=True), 402

    payload = request.get_json(silent=True) or {}
    sub = db.session.get(Submission, int(payload.get("submission_id") or 0))
    if sub is None or sub.user_id != user.id:
        abort(404)
    if sub.verdict in (V.QUEUED, V.RUNNING):
        return jsonify(error="That submission is still being judged."), 409
    if sub.verdict == V.AC:
        return jsonify(error="That one passed - there is nothing to "
                             "diagnose."), 400

    problem = sub.problem
    if problem is None or problem.status != PUBLISHED:
        abort(404)

    error, status = guard.over_cap(user)
    if error:
        return jsonify(error=error), status

    case = None
    failure = sub.first_failure
    if failure is not None and failure.is_sample:
        ordered = list(problem.tests)
        if failure.position < len(ordered):
            source = ordered[failure.position]
            case = {"stdin": source.stdin, "expected": source.expected_stdout,
                    "actual": failure.stdout, "stderr": failure.stderr}

    question = ("My submission got %s. Why does my code fail?"
                % V.LABELS.get(sub.verdict, sub.verdict))
    system, user_prompt = build("failure", problem=problem, question=question,
                                submission=sub, case=case)

    try:
        answer, model = ask(system, user_prompt)
    except TutorError as exc:
        log_tutor_message(user, None, problem, "failure", question, str(exc),
                          model="", ok=False)
        return jsonify(error=str(exc)), 502

    log_tutor_message(user, None, problem, "failure", question, answer, model)

    used = tutor_calls_since(user, _utcnow() - timedelta(hours=1))
    return jsonify(mode="failure", answer_html=render_md(answer),
                   remaining=max(0, guard.hourly_limit(user) - used))

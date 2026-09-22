from flask import (Blueprint, abort, jsonify, render_template, request,
                   url_for)

from .judge import LANGUAGES, TestCase, judge, verdicts as V
from .learning.markdown import render as render_md
from .learning.routes import complete_lessons_for_problem
from .models import (Lesson, Problem, Submission, db, first_accepted,
                     record_submission)
from .progress import award_xp
from .session import current_user, login_required

problems_bp = Blueprint("problems", __name__)

MAX_SOURCE_BYTES = 64 * 1024


def _problem_or_404(slug):
    problem = db.session.execute(
        db.select(Problem).filter_by(slug=slug)
    ).scalar_one_or_none()
    if problem is None:
        abort(404)
    return problem


@problems_bp.route("/problems/<slug>/")
@login_required
def page(slug):
    """The statement, the samples, and an editor wired to /submit."""
    problem = _problem_or_404(slug)
    user = current_user()

    solved = db.session.execute(
        db.select(Submission.id).filter_by(
            user_id=user.id, problem_id=problem.id, verdict="accepted"
        ).limit(1)
    ).scalar_one_or_none() is not None

    recent = db.session.execute(
        db.select(Submission)
        .where(Submission.user_id == user.id, Submission.problem_id == problem.id)
        .order_by(Submission.created_at.desc())
        .limit(5)
    ).scalars().all()

    # If this problem is the body of a lesson, offer the way back to it.
    lesson = db.session.execute(
        db.select(Lesson).where(Lesson.problem_id == problem.id).limit(1)
    ).scalar_one_or_none()

    return render_template(
        "problems/problem.html",
        problem=problem,
        statement=render_md(problem.statement_md),
        samples=[t for t in problem.tests if t.is_sample],
        languages=sorted(LANGUAGES),
        default_language=(user.preferred_language
                          if user.preferred_language in LANGUAGES else None),
        solved=solved,
        recent=recent,
        lesson=lesson,
        verdict_labels=V.LABELS,
    )


@problems_bp.route("/problems/<slug>/submit", methods=["POST"])
@login_required
def submit(slug):
    problem = _problem_or_404(slug)

    payload = request.get_json(silent=True) or {}
    language = payload.get("language", "")
    source = payload.get("source", "")

    if language not in LANGUAGES:
        return jsonify(error="Unsupported language."), 400
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        return jsonify(error="Submission too large."), 413

    tests = [
        TestCase(stdin=t.stdin, expected_stdout=t.expected_stdout, is_sample=t.is_sample)
        for t in problem.tests
    ]
    if not tests:
        return jsonify(error="This problem has no test cases yet."), 503

    result = judge(
        source, language, tests,
        time_limit_sec=problem.time_limit_sec,
        memory_mb=problem.memory_mb,
    )

    user = current_user()
    awarded = lesson_awarded = 0
    if result.verdict == V.AC and first_accepted(user.id, problem.id):
        # XP only on the first accepted solve. The unique constraint on
        # xp_events makes the award itself idempotent regardless.
        awarded = award_xp(user, problem.xp, "problem", str(problem.id))["awarded"]
        lesson_awarded = complete_lessons_for_problem(user, problem.id)
        db.session.commit()

    record_submission(user.id, problem, language, source, result)

    return jsonify(
        verdict=result.verdict,
        label=V.LABELS.get(result.verdict, result.verdict),
        passed=result.passed,
        total=result.total,
        max_time_ms=result.max_time_ms,
        compile_output=result.compile_output,
        xp_awarded=awarded,
        lesson_xp_awarded=lesson_awarded,
        tests=[
            {"index": t.index, "verdict": t.verdict, "time_ms": t.time_ms,
             "is_sample": t.is_sample, "stdout": t.stdout, "stderr": t.stderr}
            for t in result.tests
        ],
    )

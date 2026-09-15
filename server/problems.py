from flask import Blueprint, abort, jsonify, request

from .judge import LANGUAGES, TestCase, judge, verdicts as V
from .models import Problem, db, first_accepted, record_submission
from .session import current_user, login_required

problems_bp = Blueprint("problems", __name__)

MAX_SOURCE_BYTES = 64 * 1024


@problems_bp.route("/problems/<slug>/submit", methods=["POST"])
@login_required
def submit(slug):
    problem = db.session.execute(
        db.select(Problem).filter_by(slug=slug)
    ).scalar_one_or_none()
    if problem is None:
        abort(404)

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
    awarded = 0
    if result.verdict == V.AC and first_accepted(user.id, problem.id):
        awarded = problem.xp        # XP only on the first accepted solve

    record_submission(user.id, problem, language, source, result)

    return jsonify(
        verdict=result.verdict,
        label=V.LABELS.get(result.verdict, result.verdict),
        passed=result.passed,
        total=result.total,
        max_time_ms=result.max_time_ms,
        compile_output=result.compile_output,
        xp_awarded=awarded,
        tests=[
            {"index": t.index, "verdict": t.verdict, "time_ms": t.time_ms,
             "is_sample": t.is_sample, "stdout": t.stdout, "stderr": t.stderr}
            for t in result.tests
        ],
    )

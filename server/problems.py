import hashlib

from flask import (Blueprint, abort, flash, jsonify, redirect, render_template,
                   request, url_for)

from .judge import LANGUAGES, verdicts as V
from .learning.markdown import render as render_md
from .models import (JudgeJob, Lesson, Problem, StreakFreezeUse, Submission,
                     User, db)
from .progress import streak_state, user_today
from .ratelimit import submit_block_reason
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


# --------------------------------------------------------------------------- #
# submitting
# --------------------------------------------------------------------------- #

def _sha(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _tests_fingerprint(problem):
    """Changes whenever a test is added, edited or reordered - so a cached
    result from before the edit is never reused."""
    parts = ["%s\x1f%s\x1f%d" % (t.stdin, t.expected_stdout, int(t.is_sample))
             for t in problem.tests]
    return _sha("\x1e".join(parts))


def _cached(user, problem, language, source_hash, tests_hash):
    """The same person resubmitting byte-identical code against unchanged tests.

    Deliberately not shared across users: a cross-user cache would turn the
    judge into an oracle for whether someone else's exact source passes.
    """
    return db.session.execute(
        db.select(Submission).filter_by(
            user_id=user.id, problem_id=problem.id, language=language,
            source_hash=source_hash, tests_hash=tests_hash)
        .where(Submission.verdict.notin_([V.QUEUED, V.RUNNING, V.IE]))
        .order_by(Submission.created_at.desc()).limit(1)
    ).scalar_one_or_none()


def _streak_payload(user, since):
    """The streak as it stands, plus any freeze this submission's job spent.

    XP and streaks are settled by the worker, so the request cannot know what
    happened - but freezes are ledgered, and rows written after the
    submission was created belong to this attempt.
    """
    state = streak_state(user, user_today(user))
    spent = 0
    if since is not None:
        spent = db.session.execute(
            db.select(db.func.count()).select_from(StreakFreezeUse)
            .where(StreakFreezeUse.user_id == user.id,
                   StreakFreezeUse.created_at >= since)
        ).scalar() or 0
    state["froze"] = int(spent)
    return state


def _result_payload(problem, sub):
    """What the browser needs. Shared by the cache hit and the poll endpoint.

    Only sample cases carry input and expected output. A hidden case reports
    that it failed and nothing more - otherwise the test suite is the answer
    key, and the problem becomes fill-in-the-blank.
    """
    ordered = list(problem.tests)
    rows = []
    for t in sub.test_results:
        row = {"index": t.position, "verdict": t.verdict,
               "label": V.LABELS.get(t.verdict, t.verdict),
               "time_ms": t.time_ms, "is_sample": t.is_sample}
        if t.is_sample and t.position < len(ordered):
            case = ordered[t.position]
            row.update(stdin=case.stdin, expected=case.expected_stdout,
                       actual=t.stdout, stderr=t.stderr)
        rows.append(row)

    return {"verdict": sub.verdict,
            "label": V.LABELS.get(sub.verdict, sub.verdict),
            "passed": sub.passed, "total": sub.total,
            "max_time_ms": sub.max_time_ms,
            "compile_output": sub.compile_output or "",
            "is_public": sub.is_public,
            "tests": rows,
            "streak": _streak_payload(sub.user, sub.created_at),
            "first_failure": next((r for r in rows if r["verdict"] != V.AC), None)}


@problems_bp.route("/problems/<slug>/submit", methods=["POST"])
@login_required
def submit(slug):
    problem = _problem_or_404(slug)
    user = current_user()

    payload = request.get_json(silent=True) or {}
    language = payload.get("language", "")
    source = payload.get("source", "")

    if language not in LANGUAGES:
        return jsonify(error="Unsupported language."), 400
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        return jsonify(error="Submission too large."), 413
    if not problem.tests:
        return jsonify(error="This problem has no test cases yet."), 503

    blocked = submit_block_reason(user)
    if blocked:
        return jsonify(error=blocked), 429

    source_hash, tests_hash = _sha(source), _tests_fingerprint(problem)

    hit = _cached(user, problem, language, source_hash, tests_hash)
    if hit is not None:
        # Identical code, unchanged tests: no container, no queue.
        body = {"submission_id": hit.id, "status": "done", "cached": True}
        body.update(_result_payload(problem, hit))
        return jsonify(**body)

    sub = Submission(
        user_id=user.id, problem_id=problem.id, language=language, source=source,
        verdict=V.QUEUED, passed=0, total=len(problem.tests), max_time_ms=0,
        source_hash=source_hash, tests_hash=tests_hash,
    )
    db.session.add(sub)
    db.session.flush()
    db.session.add(JudgeJob(submission_id=sub.id))
    db.session.commit()

    return jsonify(submission_id=sub.id, status="queued"), 202


@problems_bp.route("/problems/<slug>/result/<int:sub_id>")
@login_required
def result(slug, sub_id):
    problem = _problem_or_404(slug)
    sub = db.session.get(Submission, sub_id)
    if sub is None or sub.user_id != current_user().id or sub.problem_id != problem.id:
        abort(404)

    pending = sub.verdict in (V.QUEUED, V.RUNNING)
    body = {"submission_id": sub.id, "status": "pending" if pending else "done"}
    body.update(_result_payload(problem, sub))
    return jsonify(**body)


# --------------------------------------------------------------------------- #
# community solutions
# --------------------------------------------------------------------------- #

def _has_solved(user, problem):
    return db.session.execute(
        db.select(Submission.id).filter_by(
            user_id=user.id, problem_id=problem.id, verdict=V.AC).limit(1)
    ).scalar_one_or_none() is not None


@problems_bp.route("/problems/<slug>/share/<int:sub_id>", methods=["POST"])
@login_required
def share(slug, sub_id):
    problem = _problem_or_404(slug)
    sub = db.session.get(Submission, sub_id)
    if (sub is None or sub.user_id != current_user().id
            or sub.problem_id != problem.id or sub.verdict != V.AC):
        abort(404)

    sub.is_public = not sub.is_public        # a toggle, so it can be withdrawn
    db.session.commit()
    flash("Solution shared." if sub.is_public else "Solution hidden.", "success")
    return redirect(url_for("problems.solutions", slug=problem.slug))


@problems_bp.route("/problems/<slug>/solutions/")
@login_required
def solutions(slug):
    from .community import following_ids     # imported here to avoid a cycle

    problem = _problem_or_404(slug)
    user = current_user()

    # You have to solve it before you can read how anyone else did.
    if not _has_solved(user, problem):
        flash("Solve it first - then the solutions open up.", "error")
        return redirect(url_for("problems.page", slug=problem.slug))

    rows = db.session.execute(
        db.select(Submission, User).join(User, User.id == Submission.user_id)
        .where(Submission.problem_id == problem.id,
               Submission.is_public.is_(True),
               Submission.verdict == V.AC)
        .order_by(Submission.max_time_ms.asc()).limit(40)
    ).all()

    mine = db.session.execute(
        db.select(Submission).filter_by(
            user_id=user.id, problem_id=problem.id, verdict=V.AC)
        .order_by(Submission.created_at.desc()).limit(1)
    ).scalar_one_or_none()

    return render_template("problems/solutions.html", problem=problem, rows=rows,
                           mine=mine, follows=following_ids(user))

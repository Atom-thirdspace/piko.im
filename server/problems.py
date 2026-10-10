import hashlib

from flask import (Blueprint, abort, flash, jsonify, redirect, render_template,
                   request, url_for)

from .content import visible
from .judge import LANGUAGES, verdicts as V
from .learning.markdown import render as render_md
from .models import (JudgeJob, Lesson, Problem, ProblemHint, SavedTest,
                     ScratchRun, StreakFreezeUse, Submission, User,
                     attempts_on, db, may_read_editorial, reveal_hint,
                     revealed_hint_ids, saved_tests_for, solve_percentile,
                     used_hints)
from .ratelimit import run_block_reason, run_headroom, submit_block_reason
from .progress import streak_state, user_today
from .xp_rules import solve_award, summarise, total
from .session import current_user, login_required
from .content import may_see

problems_bp = Blueprint("problems", __name__)


def _projected(user, problem):
    """What the *next* submission would pay, so the panel tells the truth
    after a failed attempt as well as before the first one."""
    parts = solve_award(problem, used_hints(user.id, problem.id),
                        attempts_on(user.id, problem.id) + 1)
    return {"total": total(parts), "summary": summarise(parts)}

MAX_SOURCE_BYTES = 64 * 1024
MAX_STDIN_BYTES = 16 * 1024

MAX_SAVED_TESTS = 20
MAX_BATCH_RUN = 10


def _problem_or_404(slug):
    problem = db.session.execute(
        db.select(Problem).filter_by(slug=slug)).scalar_one_or_none()
    if problem is None:
        abort(404)
    user = current_user()
    if may_see(problem, user):
        return problem
    from .contests import unlocked_problem_ids
    if problem.id in unlocked_problem_ids(user):
        return problem
    abort(404)



@problems_bp.route("/problems/today/")
@login_required
def today():
    from . import potd
    problem = potd.problem_for()
    if problem is None:
        flash("No problem of the day yet - the catalogue is empty.", "error")
        return redirect(url_for("dashboard.index"))
    return redirect(url_for("problems.page", slug=problem.slug))


@problems_bp.route("/problems/<slug>/")
@login_required
def page(slug):
    from . import economy, speedrun
    from .billing.service import is_pro
    problem = _problem_or_404(slug)
    user = current_user()
    pro = is_pro(user)

    solved = db.session.execute(
        db.select(Submission.id).filter_by(
            user_id=user.id, problem_id=problem.id, verdict="accepted"
        ).limit(1)
    ).scalar_one_or_none() is not None

    revealed = revealed_hint_ids(user, problem)

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
        hints=problem.hints,
        revealed_hints=revealed,
        hint_bodies={h.id: render_md(h.body_md) for h in problem.hints
                     if h.id in revealed},
        award=_projected(user, problem),
        pro=pro,
        saved_tests=saved_tests_for(user, problem) if pro else [],
        max_saved_tests=MAX_SAVED_TESTS,
        coins=economy.balance(user),
        hint_cost=economy.HINT_COST,
        speed_best=speedrun.best(user, problem),
        can_race=bool(speedrun.eligible(user, problem)),
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
            "solve": solve_percentile(sub.user_id, sub.problem_id),
            "first_failure": next((r for r in rows if r["verdict"] != V.AC), None)}


@problems_bp.route("/problems/<slug>/submit", methods=["POST"])
@login_required
def submit(slug):
    from .billing.service import is_pro
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
    db.session.add(JudgeJob(submission_id=sub.id,
                            priority=1 if is_pro(user) else 0))
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
# the Run button - the learner's own input, nothing scored
# --------------------------------------------------------------------------- #

def _run_payload(run):
    pending = run.status != "done"
    return {
        "run_id": run.id,
        "status": "pending" if pending else "done",
        "verdict": run.verdict,
        "label": V.LABELS.get(run.verdict, run.verdict),
        "stdout": run.stdout,
        "stderr": run.stderr,
        "compile_output": run.compile_output,
        "time_ms": run.time_ms,
        "error": run.error,
    }


@problems_bp.route("/problems/<slug>/run", methods=["POST"])
@login_required
def run(slug):
    problem = _problem_or_404(slug)
    user = current_user()

    payload = request.get_json(silent=True) or {}
    language = payload.get("language", "")
    source = payload.get("source", "")
    stdin = payload.get("stdin", "") or ""

    if language not in LANGUAGES:
        return jsonify(error="Unsupported language."), 400
    if not source.strip():
        return jsonify(error="There is nothing to run yet."), 400
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        return jsonify(error="Your code is too large to run."), 413
    if len(stdin.encode("utf-8")) > MAX_STDIN_BYTES:
        return jsonify(error="That input is too large."), 413

    blocked = run_block_reason(user)
    if blocked:
        return jsonify(error=blocked), 429

    row = ScratchRun(user_id=user.id, problem_id=problem.id, language=language,
                     source=source, stdin=stdin)
    db.session.add(row)
    db.session.commit()
    return jsonify(run_id=row.id, status="queued"), 202


@problems_bp.route("/problems/<slug>/run/<int:run_id>")
@login_required
def run_result(slug, run_id):
    problem = _problem_or_404(slug)
    row = db.session.get(ScratchRun, run_id)
    if row is None or row.user_id != current_user().id or row.problem_id != problem.id:
        abort(404)
    return jsonify(**_run_payload(row))


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

@problems_bp.route("/problems/<slug>/hints/<int:hint_id>", methods=["POST"])
@login_required
def reveal(slug, hint_id):
    problem = _problem_or_404(slug)
    user = current_user()
    hint = db.session.get(ProblemHint, hint_id)
    if hint is None or hint.problem_id != problem.id:
        abort(404)

    from . import economy
    already = hint.id in revealed_hint_ids(user, problem)
    if not already and hint.cost_xp:
        if not economy.spend(user, economy.HINT_COST, "hint", str(hint.id)):
            return jsonify(error="That hint costs %d coins and you have %d."
                                 % (economy.HINT_COST, economy.balance(user)),
                           coins=economy.balance(user)), 402

    reveal_hint(user, hint)
    award = _projected(user, problem)
    return jsonify(body=str(render_md(hint.body_md)),
                   award_now=award["total"], award_note=award["summary"],
                   coins=economy.balance(user))

def _pro_gate(user):
    from .billing.service import is_pro
    if is_pro(user):
        return None
    return jsonify(error="Saved test cases are a Pro feature.",
                   upgrade=True), 402


def _normalise(text):
    return "\n".join(line.rstrip()
                     for line in (text or "").strip().splitlines())


@problems_bp.route("/problems/<slug>/tests", methods=["GET"])
@login_required
def tests_list(slug):
    problem = _problem_or_404(slug)
    user = current_user()
    gate = _pro_gate(user)
    if gate:
        return gate
    return jsonify(tests=[{"id": t.id, "name": t.name, "stdin": t.stdin,
                           "expected": t.expected}
                          for t in saved_tests_for(user, problem)])

@problems_bp.route("/problems/<slug>/tests", methods=["POST"])
@login_required
def tests_save(slug):
    problem = _problem_or_404(slug)
    user = current_user()
    gate = _pro_gate(user)
    if gate:
        return gate
    
    payload = request.get_json(silent=True) or {}
    stdin = payload.get("stdin") or ""
    expected = payload.get("expected") or ""

    if len(stdin.encode("utf-8")) > MAX_STDIN_BYTES:
        return jsonify(error="That input is too large."), 413
    if len(expected.encode("utf-8")) > MAX_STDIN_BYTES:
        return jsonify(error="That expected output is too large."), 413

    held = db.session.execute(
        db.select(db.func.count()).select_from(SavedTest)
        .where(SavedTest.user_id == user.id,
               SavedTest.problem_id == problem.id)).scalar() or 0
    if held >= MAX_SAVED_TESTS:
        return jsonify(error="You have %d saved cases on this problem, which "
                             "is the limit. Delete one first."
                             % MAX_SAVED_TESTS), 409

    row = SavedTest(user_id=user.id, problem_id=problem.id,
                    name=(payload.get("name") or "Case %d" % (held + 1))[:80],
                    stdin=stdin, expected=expected)
    db.session.add(row)
    db.session.commit()
    return jsonify(id=row.id, name=row.name), 201

@problems_bp.route("/problems/<slug>/tests/<int:test_id>/delete",
                   methods=["POST"])
@login_required
def tests_delete(slug, test_id):
    problem = _problem_or_404(slug)
    user = current_user()
    gate = _pro_gate(user)
    if gate:
        return gate

    row = db.session.get(SavedTest, test_id)
    if row is None or row.user_id != user.id or row.problem_id != problem.id:
        abort(404)
    db.session.delete(row)
    db.session.commit()
    return jsonify(ok=True)


@problems_bp.route("/problems/<slug>/tests/run", methods=["POST"])
@login_required
def tests_run(slug):
    problem = _problem_or_404(slug)
    user = current_user()
    gate = _pro_gate(user)
    if gate:
        return gate

    payload = request.get_json(silent=True) or {}
    language = payload.get("language", "")
    source = payload.get("source", "")

    if language not in LANGUAGES:
        return jsonify(error="Unsupported language."), 400
    if not source.strip():
        return jsonify(error="There is nothing to run yet."), 400
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        return jsonify(error="Your code is too large to run."), 413

    blocked = run_block_reason(user)
    if blocked:
        return jsonify(error=blocked), 429

    cases = saved_tests_for(user, problem)[:MAX_BATCH_RUN]
    if not cases:
        return jsonify(error="Save a test case first."), 400

    # The per-request check above only fires once, so a batch is trimmed to the
    # headroom left rather than being allowed to blow straight past it.
    room = run_headroom(user)
    if room <= 0:
        return jsonify(error="You have no runs left this minute."), 429
    cases = cases[:room]

    queued = []
    for case in cases:
        row = ScratchRun(user_id=user.id, problem_id=problem.id,
                         language=language, source=source, stdin=case.stdin,
                         saved_test_id=case.id)
        db.session.add(row)
        db.session.flush()
        queued.append({"run_id": row.id, "test_id": case.id,
                       "name": case.name})
    db.session.commit()
    return jsonify(runs=queued, skipped=len(saved_tests_for(user, problem))
                   - len(cases)), 202


@problems_bp.route("/problems/<slug>/tests/results")
@login_required
def tests_results(slug):
    problem = _problem_or_404(slug)
    user = current_user()
    gate = _pro_gate(user)
    if gate:
        return gate
    wanted = [int(x) for x in (request.args.get("ids") or "").split(",")
              if x.strip().isdigit()][:MAX_BATCH_RUN]
    if not wanted:
        return jsonify(runs=[])

    rows = db.session.execute(
        db.select(ScratchRun).where(ScratchRun.id.in_(wanted),
                                    ScratchRun.user_id == user.id,
                                    ScratchRun.problem_id == problem.id)
    ).scalars().all()

    expected = {t.id: t.expected for t in saved_tests_for(user, problem)}
    
    out = []
    for row in rows:
        body = _run_payload(row)
        want = expected.get(row.saved_test_id)
        if row.status != "done" or want is None or not want.strip():
            body["matched"] = None
        else:
            body["matched"] = _normalise(row.stdout) == _normalise(want)
        body["test_id"] = row.saved_test_id
        out.append(body)
    return jsonify(runs=out)
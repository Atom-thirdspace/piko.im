import time

from flask import current_app

from . import verdicts as V
from .runner import TestCase, judge, run_once
from ..models import (JudgeJob, Problem, ScratchRun, _utcnow, db,
                      first_accepted, replace_test_results)
from ..progress import award_xp

# Someone is watching a spinner while a run executes, so poll tighter than we
# would for scored submissions.
POLL_SECONDS = 1
MAX_ATTEMPTS = 2

# A run is the learner's own input, so it gets less rope than a graded
# submission: shorter wall clock, and no per-problem override.
RUN_TIME_LIMIT_SEC = 5.0
RUN_MEMORY_MB = 256


def _claim():
    job = db.session.execute(
        db.select(JudgeJob).where(JudgeJob.status == "queued")
        .order_by(JudgeJob.created_at).limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if job is None:
        return None

    job.status = "running"
    job.attempts += 1
    job.claimed_at = _utcnow()
    if job.submission is not None:
        job.submission.verdict = V.RUNNING
    db.session.commit()
    return job


def _claim_run():
    run = db.session.execute(
        db.select(ScratchRun).where(ScratchRun.status == "queued")
        .order_by(ScratchRun.created_at).limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if run is None:
        return None

    run.status = "running"
    run.attempts += 1
    run.claimed_at = _utcnow()
    db.session.commit()
    return run


def execute_run(run):
    """A Run button press. Nothing here touches XP, streaks or verdicts."""
    result = run_once(run.source, run.language, stdin=run.stdin,
                      time_limit_sec=RUN_TIME_LIMIT_SEC,
                      memory_mb=RUN_MEMORY_MB)
    run.verdict = result.verdict
    run.stdout = result.stdout
    run.stderr = result.stderr
    run.compile_output = result.compile_output
    run.time_ms = result.time_ms
    run.error = result.message or ""
    run.status = "done"
    run.finished_at = _utcnow()
    db.session.commit()


def run_job(job):
    sub = job.submission
    problem = db.session.get(Problem, sub.problem_id) if sub is not None else None
    if sub is None or problem is None:
        job.status = "failed"
        job.error = "submission or problem is gone"
        job.finished_at = _utcnow()
        db.session.commit()
        return

    tests = [TestCase(stdin=t.stdin, expected_stdout=t.expected_stdout,
                      is_sample=t.is_sample) for t in problem.tests]
    result = judge(sub.source, sub.language, tests,
                   time_limit_sec=problem.time_limit_sec,
                   memory_mb=problem.memory_mb)
    
    is_first_solve = first_accepted(sub.user_id, problem.id)

    sub.verdict = result.verdict
    sub.passed, sub.total = result.passed, result.total
    sub.max_time_ms = result.max_time_ms
    sub.compile_output = result.compile_output or None
    replace_test_results(sub, result)

    # XP moves here from the request. The unique constraint on xp_events keeps
    # the award idempotent, so a retried job cannot pay twice.
    if result.verdict == V.AC and is_first_solve:
        from ..achievements import evaluate
        from ..learning.routes import complete_lessons_for_problem
        from ..models import attempts_on, record_solve, used_hints
        from ..xp_rules import solve_award
        user = sub.user
        if user is not None:
            # Counting reveals *now* is exactly "reveals before the solve":
            # the award happens once, here, at the moment of first accept.
            # attempts_on includes this submission, so 1 means first try.
            parts = solve_award(problem,
                                used_hints(user.id, problem.id),
                                attempts_on(user.id, problem.id))
            for reason, amount in parts:
                award_xp(user, amount, reason, str(problem.id))
            complete_lessons_for_problem(user, problem.id)
            db.session.commit()
            record_solve(sub)
            # Badges are evaluated off the request thread, where a handful of
            # aggregate queries costs nobody a page load.
            evaluate(user)

    if result.verdict == V.AC:
        from ..similarity import check_submission, index_submission
        fps = index_submission(sub)
        if fps:
            check_submission(sub, fps)

    job.status = "done"
    job.finished_at = _utcnow()
    db.session.commit()


def tick():
    # Runs first: a submission can wait a second, a person staring at the
    # editor cannot.
    run = _claim_run()
    if run is not None:
        run_id = run.id
        try:
            execute_run(run)
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception("scratch run %s failed", run_id)
            run = db.session.get(ScratchRun, run_id)
            if run is not None:
                run.status = "done"
                run.verdict = V.IE
                run.error = str(exc)[:500]
                run.finished_at = _utcnow()
                db.session.commit()
        return True

    job = _claim()
    if job is None:
        return False

    job_id = job.id
    try:
        run_job(job)
    except Exception as exc:                  # one bad job must not kill the worker
        db.session.rollback()
        current_app.logger.exception("judge job %s failed", job_id)
        job = db.session.get(JudgeJob, job_id)
        if job is not None:
            if job.attempts >= MAX_ATTEMPTS:
                job.status = "failed"
                job.error = str(exc)[:500]
                if job.submission is not None:
                    job.submission.verdict = V.IE
            else:
                job.status = "queued"         # one retry, then give up
            job.finished_at = _utcnow()
            db.session.commit()
    return True


def register_cli(app):
    @app.cli.command("judge-worker")
    def _worker():
        """Run forever, judging queued submissions."""
        print("judge worker started; polling every %ds" % POLL_SECONDS)
        while True:
            try:
                if not tick():
                    time.sleep(POLL_SECONDS)
            except KeyboardInterrupt:
                print("stopping")
                break
            except Exception:
                app.logger.exception("worker loop error")
                time.sleep(POLL_SECONDS)

    @app.cli.command("judge-prune")
    def _prune():
        """Delete scratch runs older than a few hours."""
        from ..models import prune_scratch_runs
        print("pruned %d scratch runs" % prune_scratch_runs())

    @app.cli.command("judge-drain")
    def _drain():
        """Run every queued job once and exit - handy in CI and in tests."""
        count = 0
        while tick():
            count += 1
        print("drained %d jobs" % count)

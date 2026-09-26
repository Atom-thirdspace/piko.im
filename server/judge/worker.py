"""The process that actually runs learner code.

Run at least one alongside the web app:  flask judge-worker

Without a worker nothing is ever judged - submissions sit at 'queued'
forever. Jobs are claimed with SKIP LOCKED, so several workers can share one
database without fighting over the same submission.
"""

import time

from flask import current_app

from . import verdicts as V
from .runner import TestCase, judge
from ..models import (JudgeJob, Problem, _utcnow, db, first_accepted,
                      replace_test_results)
from ..progress import award_xp

POLL_SECONDS = 2
MAX_ATTEMPTS = 2


def _claim():
    """Take the oldest queued job, skipping ones another worker holds."""
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

    sub.verdict = result.verdict
    sub.passed, sub.total = result.passed, result.total
    sub.max_time_ms = result.max_time_ms
    sub.compile_output = result.compile_output or None
    replace_test_results(sub, result)

    # XP moves here from the request. The unique constraint on xp_events keeps
    # the award idempotent, so a retried job cannot pay twice.
    if result.verdict == V.AC and first_accepted(sub.user_id, problem.id):
        from ..learning.routes import complete_lessons_for_problem
        user = sub.user
        if user is not None:
            award_xp(user, problem.xp, "problem", str(problem.id))
            complete_lessons_for_problem(user, problem.id)

    job.status = "done"
    job.finished_at = _utcnow()
    db.session.commit()


def tick():
    """One pass. True when it did work, so the caller can skip its sleep."""
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

    @app.cli.command("judge-drain")
    def _drain():
        """Run every queued job once and exit - handy in CI and in tests."""
        count = 0
        while tick():
            count += 1
        print("drained %d jobs" % count)

"""Run an author's reference solution against their own test cases.

Blank expected outputs are filled in from the run, so the normal way to
write a problem is inputs plus a reference and let the judge produce the
answers. Anything already filled in is checked, not overwritten.
"""

from ..judge import TestCase, judge
from ..judge import verdicts as V
from ..models import _utcnow, db

MAX_OUTPUT = 4000
BROKEN = (V.TLE, V.MLE, V.RE, V.IE)


def run_reference(problem):
    """Returns (ok, message). On success the problem is marked verified."""
    tests = list(problem.tests)
    if not tests:
        return False, "Add a test case first."
    if not (problem.reference_source or "").strip():
        return False, "Add a reference solution first."

    cases = [TestCase(stdin=t.stdin, expected_stdout="", is_sample=False)
             for t in tests]
    result = judge(problem.reference_source, problem.reference_language, cases,
                   time_limit_sec=problem.time_limit_sec,
                   memory_mb=problem.memory_mb,
                   stop_on_first_failure=False)

    if result.verdict == V.CE:
        return False, ("The reference does not compile. %s"
                       % (result.compile_output or "")[:300])
    if len(result.tests) != len(tests):
        return False, ("The judge returned %d outcomes for %d tests."
                       % (len(result.tests), len(tests)))

    filled, wrong = 0, []
    for test, outcome in zip(tests, result.tests):
        n = outcome.index + 1
        if outcome.verdict in BROKEN:
            return False, "Test %d: the reference %s." % (n, outcome.verdict)
        if len(outcome.stdout) > MAX_OUTPUT:
            return False, "Test %d: the reference printed too much." % n
        if not (test.expected_stdout or "").strip():
            test.expected_stdout = outcome.stdout
            filled += 1
        elif test.expected_stdout.strip() != outcome.stdout.strip():
            wrong.append(n)

    if wrong:
        db.session.rollback()
        return False, ("The reference disagrees with your expected output on "
                       "test %s." % ", ".join(str(n) for n in wrong))

    problem.verified_at = _utcnow()
    db.session.commit()
    if filled:
        return True, ("Verified. Filled in the expected output for %d test%s."
                      % (filled, "" if filled == 1 else "s"))
    return True, "Verified: the reference passes all %d tests." % len(tests)

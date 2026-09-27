from ..judge import TestCase, judge, verdicts as V
MAX_OUTPUT = 4000

class Rejected(Exception):
    """The draft failed a check and must not reach a reviewer."""

def _run(draft, inputs):
    """Real outputs for each input.

    judge() compares against expected_stdout, so passing empty strings makes
    every case 'fail' - which is fine, because what we want is the stdout it
    hands back, not the verdict.
    """
    cases = [TestCase(stdin=s, expected_stdout="", is_sample=False)
             for s in inputs]
    result = judge(draft.reference_source, draft.reference_language, cases,
                   time_limit_sec=draft.time_limit_sec,
                   memory_mb=draft.memory_mb,
                   stop_on_first_failure=False)

    if result.verdict == V.CE:
        raise Rejected("reference solution does not compile: %s"
                       % (result.compile_output or "")[:300])
    if len(result.tests) != len(inputs):
        raise Rejected("judge returned %d outcomes for %d inputs"
                       % (len(result.tests), len(inputs)))

    outputs = []
    for outcome in result.tests:
        # WA is expected (we compared against ""). Anything else is real.
        if outcome.verdict in (V.TLE, V.MLE, V.RE, V.IE):
            raise Rejected("reference solution %s on input %d"
                           % (outcome.verdict, outcome.index))
        if len(outcome.stdout) > MAX_OUTPUT:
            raise Rejected("reference output is enormous on input %d"
                           % outcome.index)
        outputs.append(outcome.stdout)
    return outputs

def verify(draft):
    """Returns the payload dict for a GeneratedProblem, or raises Rejected."""
    if not draft.inputs:
        raise Rejected("no inputs")

    outputs = _run(draft, draft.inputs)

    if any(not o.strip() for o in outputs):
        raise Rejected("reference produced empty output for some input")

    if len(set(outputs)) == 1 and len(outputs) > 2:
        raise Rejected("every input gives the same output")
    
    if _run(draft, draft.inputs) != outputs:
        raise Rejected("reference solution is not deterministic")

    tests = [{"stdin": s, "expected_stdout": o,
              "is_sample": i < draft.sample_count}
             for i, (s, o) in enumerate(zip(draft.inputs, outputs))]

    return {
        "tests": tests,
        "hints": [{"body": b, "cost_xp": c} for b, c in draft.hints],
        "reference_source": draft.reference_source,
        "reference_language": draft.reference_language,
        "time_limit_sec": draft.time_limit_sec,
        "memory_mb": draft.memory_mb,
    }

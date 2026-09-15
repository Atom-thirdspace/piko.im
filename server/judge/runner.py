from dataclasses import dataclass, field
from typing import List, Optional
from . import verdicts as V
from .languages import get_language
from .sandbox import Sandbox, SandboxError

@dataclass
class TestCase:
    stdin: str
    expected_stdout: str
    is_sample: bool = False

@dataclass
class TestOutcome:
    index: int
    verdict: str
    time_ms: int
    stdout: str = ""
    stderr: str = ""
    is_sample: bool = False

@dataclass
class JudgeResult:
    verdict: str
    tests: List[TestOutcome] = field(default_factory=list)
    compile_output: str = ""
    max_time_ms: int = 0
    passed: int = 0
    total: int = 0
    message: str = ""

def judge(source, language_key, tests, time_limit_sec=2.0, memory_mb=None,
          stop_on_first_failure=True):
    try:
        lang = get_language(language_key)
    except KeyError as exc:
        return JudgeResult(verdict=V.IE, message=str(exc))

    if not source.strip():
        return JudgeResult(verdict=V.CE, compile_output="Empty submission.")

    memory_mb = memory_mb or lang.default_memory_mb
    result = JudgeResult(verdict=V.AC, total=len(tests))

    try:
        with Sandbox(image=lang.image, memory_mb=memory_mb) as box:
            box.put_file(lang.source_name, source)

            if lang.compile_cmd:
                comp = box.exec(lang.compile_cmd, timeout_sec=lang.compile_timeout_sec)
                if comp.timed_out:
                    return JudgeResult(verdict=V.CE, total=len(tests),
                                       compile_output="Compilation timed out.")
                if comp.exit_code != 0:
                    return JudgeResult(verdict=V.CE, total=len(tests),
                                       compile_output=comp.stderr or comp.stdout)
                result.compile_output = comp.stderr

            for i, test in enumerate(tests):
                run = box.exec(lang.run_cmd, stdin=test.stdin,timeout_sec=time_limit_sec)
                if run.timed_out:
                    verdict = V.TLE
                elif run.oom_killed:
                    verdict = V.MLE
                elif run.exit_code != 0:
                    verdict = V.RE
                elif V.outputs_match(test.expected_stdout, run.stdout):
                    verdict = V.AC
                else:
                    verdict = V.WA

                result.tests.append(TestOutcome(
                    index=i, verdict=verdict, time_ms=run.duration_ms,
                    # Never leak hidden-test output; samples are safe to show.
                    stdout=run.stdout if test.is_sample else "",
                    stderr=run.stderr if verdict == V.RE else "",
                    is_sample=test.is_sample,
                ))
                result.max_time_ms = max(result.max_time_ms, run.duration_ms)

                if verdict == V.AC:
                    result.passed += 1
                else:
                    result.verdict = verdict
                    # A TLE destroys the container, so we cannot continue regardless.
                    if stop_on_first_failure or verdict == V.TLE:
                        break

    except SandboxError as exc:
        return JudgeResult(verdict=V.IE, total=len(tests), message=str(exc))

    return result
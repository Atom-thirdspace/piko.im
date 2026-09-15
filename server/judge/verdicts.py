AC = "accepted"
WA = "wrong_answer"
TLE = "time_limit_exceeded"
MLE = "memory_limit_exceeded"
RE = "runtime_error"
CE = "compile_error"
IE = "internal_error"          # our bug, not the user's

LABELS = {
    AC: "Accepted",
    WA: "Wrong Answer",
    TLE: "Time Limit Exceeded",
    MLE: "Memory Limit Exceeded",
    RE: "Runtime Error",
    CE: "Compilation Error",
    IE: "Internal Error",
}


def normalize(text):
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def outputs_match(expected, actual):
    return normalize(expected) == normalize(actual)

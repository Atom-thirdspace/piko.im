AC = "accepted"
OK = "ok"                       # a Run finished; nothing was scored
WA = "wrong_answer"
TLE = "time_limit_exceeded"
MLE = "memory_limit_exceeded"
RE = "runtime_error"
CE = "compile_error"
OLE = "output_limit_exceeded"
IE = "internal_error"          # our bug, not the user's
QUEUED = "queued"              # waiting for a worker
RUNNING = "running"            # a worker has it

LABELS = {
    AC: "Accepted",
    OK: "Finished",
    WA: "Wrong Answer",
    TLE: "Time Limit Exceeded",
    MLE: "Memory Limit Exceeded",
    RE: "Runtime Error",
    CE: "Compilation Error",
    OLE: "Output Limit Exceeded",
    IE: "Internal Error",
    QUEUED: "Queued",
    RUNNING: "Running",
}

QUEUED = "queued"
RUNNING = "running"



def normalize(text):
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def outputs_match(expected, actual):
    return normalize(expected) == normalize(actual)
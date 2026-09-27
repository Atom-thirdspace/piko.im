import io
import subprocess
import tarfile
import threading
import time
import uuid
from dataclasses import dataclass

DOCKER = "docker"
MAX_CAPTURE_BYTES = 64 * 1024

# What we keep is MAX_CAPTURE_BYTES, but truncating after the fact does nothing
# for the host: capture_output=True buffers the whole stream in our memory
# first. A submission that only prints can push hundreds of MB through the pipe
# inside its time limit, and the container's --memory does not cover it - those
# bytes live in the worker, not the cgroup. So we stop reading at this ceiling
# and kill the run.
MAX_STREAM_BYTES = 4 * 1024 * 1024

class SandboxError(RuntimeError):
    """Docker itself failed - not the user's code."""


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    oom_killed: bool = False
    output_exceeded: bool = False


def _tar_bytes(name, data, mode=0o644):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        info = tarfile.TarInfo(name)
        info.size = len(data)
        info.mode = mode
        tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()

def _decode(raw):
    if raw is None:
        return ""
    if len(raw) > MAX_CAPTURE_BYTES:
        raw = raw[:MAX_CAPTURE_BYTES]
        return raw.decode("utf-8", "replace") + "\n...[output truncated]"
    return raw.decode("utf-8", "replace")

def _drain(stream, sink, limit, overflow):
    """Read until EOF, keeping at most `limit` bytes; flag and stop past it."""
    total = 0
    try:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                return
            total += len(chunk)
            if total > limit:
                overflow.set()
                return
            sink.append(chunk)
    except (OSError, ValueError):
        return                      # pipe closed under us; nothing to salvage
    finally:
        try:
            stream.close()
        except (OSError, ValueError):
            pass


def _feed(stream, data):
    """Write stdin on its own thread so a program that ignores it cannot wedge us."""
    try:
        if data:
            stream.write(data)
        stream.flush()
    except (OSError, ValueError):
        pass                        # child exited early; its output still counts
    finally:
        try:
            stream.close()
        except (OSError, ValueError):
            pass


class Sandbox:
    def __init__(self, image, memory_mb=256, pids=64, cpus="1.0", workdir_mb=64):
        self.image = image
        self.memory_mb = memory_mb
        self.pids = pids
        self.cpus = cpus
        self.workdir_mb = workdir_mb
        self.cid = None

    def __enter__(self):
        self.create()
        return self

    def __exit__(self, *exc):
        self.destroy()
        return False

    def create(self):
        name = "piko-judge-" + uuid.uuid4().hex[:12]
        cmd = [
            DOCKER, "create",
            "--name", name,
            "--network", "none",                       # no egress, no DNS
            "--memory", f"{self.memory_mb}m",
            "--memory-swap", f"{self.memory_mb}m",     # equal => swap disabled
            "--pids-limit", str(self.pids),
            "--cpus", str(self.cpus),
            "--user", "65534:65534",                   # nobody
            "--security-opt", "no-new-privileges",
            "--cap-drop", "ALL",
            "--read-only",                             # rootfs immutable
            # /work must be exec: Docker's --tmpfs defaults include noexec,
            # which would make every compiled binary fail with "Permission denied".
            "--tmpfs", f"/work:rw,exec,nosuid,nodev,size={self.workdir_mb}m,mode=1777",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777",
            "--workdir", "/work",
            "--entrypoint", "",                        # ignore image entrypoints
            self.image,
            "sleep", "3600",
        ]
        proc = subprocess.run(cmd, capture_output=True)
        if proc.returncode != 0:
            raise SandboxError("docker create failed: " + _decode(proc.stderr))
        self.cid = proc.stdout.decode().strip()

        proc = subprocess.run([DOCKER, "start", self.cid], capture_output=True)
        if proc.returncode != 0:
            raise SandboxError("docker start failed: " + _decode(proc.stderr))
        return self.cid

    def put_file(self, name, text, mode=0o644):
        tar = _tar_bytes(name, text.encode("utf-8"), mode=mode)
        proc = subprocess.run(
            [DOCKER, "cp", "-", f"{self.cid}:/work"], input=tar, capture_output=True
        )
        if proc.returncode != 0:
            raise SandboxError("docker cp failed: " + _decode(proc.stderr)) 


    def exec(self, argv, stdin="", timeout_sec=5, output_limit=MAX_STREAM_BYTES):
        started = time.monotonic()
        proc = subprocess.Popen(
            [DOCKER, "exec", "-i", self.cid] + list(argv),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        out, err = [], []
        overflow = threading.Event()
        for target, args in (
            (_feed, (proc.stdin, stdin.encode("utf-8"))),
            (_drain, (proc.stdout, out, output_limit, overflow)),
            (_drain, (proc.stderr, err, output_limit, overflow)),
        ):
            t = threading.Thread(target=target, args=args, daemon=True)
            t.start()

        timed_out = False
        deadline = started + timeout_sec
        while proc.poll() is None:
            if overflow.is_set():
                break
            if time.monotonic() >= deadline:
                timed_out = True
                break
            time.sleep(0.005)

        duration_ms = int((time.monotonic() - started) * 1000)

        if timed_out or overflow.is_set():
            # Killing the client leaves the process running inside the
            # container, so the container itself has to go - same as before.
            self.destroy()
            proc.kill()
            proc.wait()
            return ExecResult(
                exit_code=-1,
                stdout="" if timed_out else _decode(b"".join(out)),
                stderr="", duration_ms=duration_ms,
                timed_out=timed_out, output_exceeded=overflow.is_set(),
            )

        return ExecResult(
            exit_code=proc.returncode,
            stdout=_decode(b"".join(out)),
            stderr=_decode(b"".join(err)),
            duration_ms=duration_ms,
            # 137 == SIGKILL, which for us almost always means the cgroup OOM killer.
            oom_killed=proc.returncode == 137,
        )

    def destroy(self):
        if self.cid:
            subprocess.run([DOCKER, "rm", "-f", self.cid], capture_output=True, timeout=30)
            self.cid = None
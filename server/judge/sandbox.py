import io
import subprocess
import tarfile
import time
import uuid
from dataclasses import dataclass

DOCKER = "docker"
MAX_CAPTURE_BYTES=64*1024

class SandboxError(RuntimeError):


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    oom_killed: bool = False


def tar_bytes(name,data,mode=0o644):
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


    def exec(self, argv, stdin="", timeout_sec=5):
        started = time.monotonic()
        cmd = [DOCKER, "exec", "-i", self.cid] + list(argv)
        try:
            proc = subprocess.run(
                cmd, input = stdin.encode("utf-8"),
                capture_output=True, timeout=timeout_sec,
            )
        except subprocess.TimeoutExpired:
            self.destroy()
            return ExecResult(
                exit_code=-1, stdout="", stderr="",
                duration_ms=int((time.monotonic() - started) * 1000),
                timed_out=True,
            )

        duration_ms = int((time.monotonic() - started) * 1000)
        return ExecResult(
            exit_code=proc.returncode,
            stdout=_decode(proc.stdout),
            stderr=_decode(proc.stderr),
            duration_ms=duration_ms,
            # 137 == SIGKILL, which for us almost always means the cgroup OOM killer.
            oom_killed=proc.returncode == 137,
        )

    def destory(self):
        if self.cid:
            subprocess.run([DOCKER, "rm", "-f", self.cid], capture_output=True, timeout=30)
            self.cid = None
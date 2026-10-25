import platform
import shutil
import subprocess
from pathlib import Path

from .output import Fail

TIMEOUT = 10

GEN_STUB = '''\
"""Prints one random test case.  Called as: python gen.py <seed> [size]"""
import random
import sys

seed = int(sys.argv[1])
size = int(sys.argv[2]) if len(sys.argv) > 2 else 8
random.seed(seed)

values = [random.randint(1, 20) for _ in range(size)]
print(len(values))
print(" ".join(str(v) for v in values))
'''

BRUTE_STUB = '''\
"""The obviously-correct solution.  Slow is fine - it only sees small cases."""
import sys


def main():
    data = sys.stdin.read().split()
    n = int(data[0])
    values = [int(x) for x in data[1:1 + n]]
    print(max(values))


if __name__ == "__main__":
    main()
'''

def _exe(name):
    return name + ".exe" if platform.system() == "Windows" else name

class Program:
    def __init__(self, path, workdir):
        self.path = Path(path)
        if not self.path.exists():
            raise Fail("No such file: %s" % self.path)
        self.workdir = Path(workdir)
        self.cmd = self._build()

    def _build(self):
        suffix = self.path.suffix.lower()
        if suffix == ".py":
            from .runner import _python
            return [_python(), "-u", str(self.path)]

        if suffix in (".cpp", ".cc", ".cxx"):
            if not shutil.which("g++"):
                raise Fail("g++ isn't installed, so %s can't be built." % self.path.name)
            target = self.workdir / _exe(self.path.stem)
            proc = subprocess.run(
                ["g++", "-O2", "-std=c++17", "-o", str(target),
                 str(self.path)], capture_output=True, text=True, timeout=120)
            if proc.returncode != 0:
                raise Fail("Compiling %s failed:\n\n%s"
                           % (self.path.name, proc.stderr or proc.stdout))
            return [str(target)]

        return [str(self.path)]

    def run(self, args=(), stdin_text=""):
        try:
            proc = subprocess.run(
                self.cmd + [str(a) for a in args], input=stdin_text,
                capture_output=True, text=True, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            return None, "timed out after %ds" % TIMEOUT
        except OSError as exc:
            return None, str(exc)
        if proc.returncode != 0:
            return None, (proc.stderr or "").strip()[:400] or "non-zero exit"
        return proc.stdout, ""

def smallest_failing(fails, seed, size):
    low, high, best = 1,size,size
    while low <= high:
        mid = (low + high) // 2
        if fails(seed,mid):
            best, high = mid, mid - 1
        else:
            low = mid = 1
    return best


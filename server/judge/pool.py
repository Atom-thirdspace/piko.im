import queue
import subprocess
import threading
import time

from .languages import LANGUAGES
from .sandbox import DOCKER, Sandbox, SandboxError

WARM_PER_IMAGE = 2
FILL_TIMEOUT_SEC = 30

class _Slot:
    __slots__ = ("image", "memory_mb")

    def __init__(self, image, memory_mb):
        self.image = image
        self.memory_mb = memory_mb

    def key(self):
        return (self.image, self.memory_mb)

class WarmPool:
    def __init__(self, warm_per_image=WARM_PER_IMAGE):
        self.warm_per_image = warm_per_image
        self._ready = {}
        self._lock = threading.Lock()
        self._started = False
        self._closed = False


    def _bucket(self, key):
        with self._lock:
            if key not in self._ready:
                self._ready[key] = queue.Queue()
            return self._ready[key]

    def _make(self, image, memory_mb):
        box = Sandbox(image=image, memory_mb=memory_mb)
        box.create()
        return box

    def _fill_one(self, image, memory_mb):
        if self._closed:
            return
        try:
            box = self._make(image, memory_mb)
        except SandboxError:
            return                      # docker is down; acquire() will say so
        # A fill started before drain() can land after it. Checking again
        # here is what stops shutdown leaving containers behind.
        if self._closed:
            box.destroy()
            return
        self._bucket((image, memory_mb)).put(box)

    def warm(self):
        if self._started:
            return
        self._started = True
        for lang in LANGUAGES.values():
            for _ in range(self.warm_per_image):
                threading.Thread(
                    target=self._fill_one,
                    args=(lang.image, lang.default_memory_mb),
                    daemon=True).start()

    def acquire(self, image, memory_mb):
        try:
            box = self._bucket((image, memory_mb)).get_nowait()
        except queue.Empty:
            box = self._make(image, memory_mb)
        else:
            if not _alive(box):
                box = self._make(image, memory_mb)
        threading.Thread(target=self._fill_one, args=(image, memory_mb),
                         daemon=True).start()
        return box

    def recycle(self, box):
        threading.Thread(target=box.destroy, daemon=True).start()

    def drain(self, settle_sec=1.0):
        self._closed = True
        deadline = time.monotonic() + settle_sec
        removed = 0
        while True:
            with self._lock:
                buckets = list(self._ready.values())
            emptied = True
            for bucket in buckets:
                while True:
                    try:
                        bucket.get_nowait().destroy()
                        removed += 1
                        emptied = False
                    except queue.Empty:
                        break
            if emptied and time.monotonic() >= deadline:
                return removed
            time.sleep(0.05)

def _alive(box):
    if box.dead:
        return False
    proc = subprocess.run(
        [DOCKER, "inspect", "-f", "{{.State.Running}}", box.cid],
        capture_output=True, timeout=10)
    return proc.returncode == 0 and proc.stdout.strip() == b"true"

def pull_images():
    seen, missing = set(), []
    for lang in LANGUAGES.values():
        if lang.image in seen:
            continue
        seen.add(lang.image)
        proc = subprocess.run([DOCKER, "pull", lang.image],
                              capture_output=True, timeout=600)
        if proc.returncode != 0:
            missing.append(lang.image)
    return missing

POOL = WarmPool()


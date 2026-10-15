import threading
import time

from .admin_gate import is_admin

_lock = threading.Lock()
_store = {}

DEFAULT_TTL = 120.0


def may_preview(user):
    return bool(user is not None
                and (is_admin(user) or getattr(user, "is_author", False)))


def cached(key, build, ttl=DEFAULT_TTL, user=None):
    if may_preview(user):
        return build()

    now = time.monotonic()
    with _lock:
        hit = _store.get(key)
        if hit is not None and now - hit[0] < ttl:
            return hit[1]

    value = build()
    with _lock:
        _store[key] = (now, value)
    return value


def drop(prefix=""):
    with _lock:
        stale = [k for k in _store if k.startswith(prefix)]
        for key in stale:
            _store.pop(key, None)
    return len(stale)


def stats():
    now = time.monotonic()
    with _lock:
        return {key: round(now - at, 1) for key, (at, _v) in _store.items()}

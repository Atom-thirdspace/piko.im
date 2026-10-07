from functools import wraps
from flask import g, has_request_context

def per_request(key_fn):
    def outer(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            if not has_request_context():
                return fn(*args, **kwargs)
            cache = getattr(g, "_memo", None)
            if cache is None:
                cache = g._memo = {}
            key = (fn.__name__, key_fn(*args, **kwargs))
            if key not in cache:
                cache[key] = fn(*args, **kwargs)
            return cache[key]
        return inner
    return outer
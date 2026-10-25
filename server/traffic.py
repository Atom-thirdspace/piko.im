import hashlib
import os
import threading
import time
from collections import deque
from datetime import date, timedelta


from flask import g, request

from .models import PageEvent, _utcnow, db

FLUSH_EVERY = 5.0
FLUSH_AT = 100
BUFFER_MAX = 5000
RETAIN_DAYS = 90
SKIP_PREFIXES = ("/static/", "/favicon", "/healthz", "/robots.txt")

BOT_MARKERS = ("bot", "crawl", "spider", "slurp", "curl/", "wget/",
               "python-requests", "headlesschrome", "monitor", "uptime")

_buffer = deque(maxlen=BUFFER_MAX)
_lock = threading.Lock()
_thread = None
_dropped = 0

def _visitor_hash(ip, agent):
    salt = "%s|%s" % (os.environ.get("SECRET_KEY", "dev"),
                      date.today().isoformat())
    raw = "%s|%s|%s" % (salt, ip or "", (agent or "")[:200])
    return hashlib.blake2b(raw.encode("utf-8"), digest_size=12).hexdigest()

def _is_bot(agent):
    low = (agent or "").lower()
    return any(marker in low for marker in BOT_MARKERS)

def _referrer_host(value):
    if not value:
        return ""
    try:
        from urllib.parse import urlsplit
        host = urlsplit(value).netloc.lower()
    except ValueError:
        return ""
    return "" if host == (request.host or "").lower() else host[:120]

def _route_name():
    rule = getattr(request.url_rule, "rule", None)
    return (rule or "<unmatched>")[:120]

def _flush(app):
    with _lock:
        if not _buffer:
            return 0
        batch = [_buffer.popleft() for _ in range(len(_buffer))]

    with app.app_context():
        try:
            db.session.execute(db.insert(PageEvent), batch)
            db.session.commit()
        except Exception:
            # Analytics must never take the site down, and a failed batch
            # is not worth retrying into a growing backlog.
            db.session.rollback()
            app.logger.exception("traffic flush failed, dropped %d",
                                 len(batch))
            return 0
    return len(batch)


def _loop(app):
    while True:
        time.sleep(FLUSH_EVERY)
        try:
            _flush(app)
        except Exception:
            pass

def install(app):
    if os.environ.get("PIKO_TRAFFIC") == "off":
        return

    @app.before_request
    def _mark_start():
        g._traffic_started = time.perf_counter()

    @app.after_request
    def _record(response):
        global _dropped

        path = request.path or "/"
        if request.method in ("OPTIONS", "HEAD"):
            return response
        if any(path.startswith(prefix) for prefix in SKIP_PREFIXES):
            return response

        started = getattr(g, "_traffic_started", None)
        ms = int((time.perf_counter() - started) * 1000) if started else 0

        user = getattr(g, "api_user", None)
        if user is None:
            from .session import current_user
            try:
                user = current_user()
            except Exception:
                user = None
        agent = request.headers.get("User-Agent", "")
        row = {
            "at": _utcnow(),
            "route": _route_name(),
            "method": request.method[:8],
            "status": response.status_code,
            "ms": ms,
            "user_id": user.id if user is not None else None,
            "visitor": _visitor_hash(request.remote_addr, agent),
            "referrer": _referrer_host(request.headers.get("Referer")),
            "bot": _is_bot(agent),
        }

        with _lock:
            if len(_buffer) == BUFFER_MAX:
                _dropped += 1
            _buffer.append(row)
            ready = len(_buffer) >= FLUSH_AT

        if ready:
            threading.Thread(target=_flush, args=(app,), daemon=True).start()
        return response

    global _thread
    if _thread is None:
        _thread = threading.Thread(target=_loop, args=(app,), daemon=True)
        _thread.start()

def buffered():
    return len(_buffer), _dropped

def prune(days=RETAIN_DAYS):
    cutoff = _utcnow() - timedelta(days=days)
    removed = db.session.execute(
        db.delete(PageEvent).where(PageEvent.at < cutoff)).rowcount
    db.session.commit()
    return removed or 0


def register_cli(app):
    @app.cli.command("traffic-prune")
    def _prune():
        print("removed %d" % prune())
        
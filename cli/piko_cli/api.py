import hashlib
import json
import time

import requests

from . import config
from .output import Fail

TIMEOUT = 20

def _cache_path(url):
    key = hashlib.blake2b(url.encode("utf-8"), digest_size=16).hexdigest()
    return config.CACHE / (key + ".json")

def _load_cache(url):
    try:
        return json.loads(_cache_path(url).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

def _save_cache(url, etag, body):
    if not etag:
        return
    try:
        config.CACHE.mkdir(parents=True, exist_ok=True)
        _cache_path(url).write_text(
            json.dumps({"etag": etag, "body": body}), encoding="utf-8")
    except OSError:
        pass

CLIENT_ID = "piko-cli"


def _oauth(form):
    """Talk to /oauth/token, which lives on the site, not under /api/v1."""
    try:
        resp = requests.post(config.site() + "/oauth/token", data=form,
                             timeout=TIMEOUT)
    except requests.Timeout:
        raise Fail("Piko took too long to answer. Try again.")
    except requests.RequestException:
        raise Fail("Couldn't reach Piko at %s." % config.site())

    try:
        body = resp.json() if resp.content else {}
    except ValueError:
        raise Fail("Piko sent back something unreadable.")

    if resp.status_code != 200:
        raise Fail(body.get("error_description") or body.get("error")
                   or "Sign-in failed (%s)." % resp.status_code)
    return body


def exchange_code(code, verifier, redirect_uri):
    return _oauth({"grant_type": "authorization_code", "client_id": CLIENT_ID,
                   "code": code, "code_verifier": verifier,
                   "redirect_uri": redirect_uri})


def refresh_if_needed():
    """Swap a nearly-dead access token for a fresh one, quietly.

    Access tokens last an hour, so without this every command would start
    failing mid-session an hour after signing in.
    """
    refresh, expires_at = config.oauth_state()
    if not refresh or expires_at - time.time() > 60:
        return
    body = _oauth({"grant_type": "refresh_token", "client_id": CLIENT_ID,
                   "refresh_token": refresh})
    config.save_oauth(body["access_token"], body.get("refresh_token", refresh),
                      body.get("expires_in", 3600))


def revoke_token():
    refresh, _ = config.oauth_state()
    if not refresh:
        return False
    try:
        requests.post(config.site() + "/oauth/revoke",
                      data={"token": refresh, "client_id": CLIENT_ID},
                      timeout=TIMEOUT)
    except requests.RequestException:
        return False
    return True


def _headers(auth=True):
    headers = {"Accept": "application/json", "User-Agent": "piko-cli"}
    if auth:
        refresh_if_needed()
    tok = config.token() if auth else ""
    if tok:
        headers["Authorization"] = "Bearer " + tok
    return headers


def _unwrap(resp):
    if resp.status_code == 401:
        raise Fail("That API key isn't valid. Run `piko login` again.")
    if resp.status_code == 403:
        raise Fail("Your key doesn't carry the scope this needs.\n"
                   "Make a new one at /settings/#api with the right scopes.")
    if resp.status_code == 404:
        raise Fail("Not found.")
    if resp.status_code == 429:
        wait = resp.headers.get("Retry-After", "60")
        raise Fail("Rate limited. Wait %s seconds." % wait)

    try:
        body = resp.json()
    except ValueError:
        raise Fail("Piko sent back something unreadable")
    
    if resp.status_code >= 400:
        # Most errors are {"error": {"code", "message"}}, but the CSRF guard
        # and Flask's own handlers answer with a bare string.
        detail = (body or {}).get("error") if isinstance(body, dict) else None
        if isinstance(detail, dict):
            detail = detail.get("message")
        raise Fail(detail or "Piko returned %s." % resp.status_code)
    return body


def get(path, params=None, auth=True, use_cache=True):
    url = config.api_base() + path
    headers = _headers(auth)

    cached = _load_cache(url) if use_cache and not params else None
    if cached and cached.get("etag"):
        headers["If-None-Match"] = cached["etag"]

    try:
        resp = requests.get(url, params=params, headers=headers,
                            timeout=TIMEOUT)
    except requests.Timeout:
        raise Fail("Piko took too long to answer. Try again.")
    except requests.RequestException:
        raise Fail("Couldn't reach Piko at %s." % config.api_base())

    if resp.status_code == 304 and cached:
        return cached["body"]

    body = _unwrap(resp)
    if not params:
        _save_cache(url, resp.headers.get("ETag"), body)
    return body

def post(path, payload, timeout=None):
    url = config.api_base() + path
    headers = _headers(True)
    headers["Content-Type"] = "application/json"
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout or TIMEOUT)
    except requests.Timeout:
        raise Fail("Piko took too long to answer. Try again.")
    except requests.RequestException:
        raise Fail("Couldn't reach Piko at %s." % config.api_base())
    return _unwrap(resp)

    

def whoami():
    return get("/me", use_cache=False)

def tracks():
    return get("/tracks", auth=False)


def track(slug):
    return get("/tracks/%s" % slug, auth=False)

def lesson(track_slug, unit_slug, lesson_slug):
    return get("/tracks/%s/%s/%s" % (track_slug, unit_slug, lesson_slug),
               auth=False)

def languages():
    return get("/languages", auth=False)


def problems(topic=None, difficulty=None, q=None, page=1, per_page=25):
    params = {"page": page, "per_page": per_page}
    if topic:
        params["topic"] = topic
    if difficulty:
        params["difficulty"] = difficulty
    if q:
        params["q"] = q
    return get("/problems", params=params, auth=False)


def problem(slug, fresh=False):
    # Sent with the key: the server adds the editorial when you have earned
    # it. The ETag cache is keyed on the url alone, so that read skips it.
    return get("/problems/%s" % slug, use_cache=not fresh)

def potd():
    return get("/potd", use_cache=False)

def next_up():
    return get("/me/next", use_cache=False)

def streak():
    return get("/me/streak", use_cache=False)

def submit(slug, language, source):
    return post("/submissions", {"problem": slug, "language": language,
                                 "source": source})

def submission(sub_id):
    return get("/submissions/%d" % sub_id, use_cache=False)
 
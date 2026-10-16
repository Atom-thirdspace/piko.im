import hashlib
import json

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
            json.dump({"etag": etag, "body": body}), encoding="utf-8")
    except OSError:
        pass

def get(path, params=None, auth=True, use_cache=True):
    url = config.api_base() + path
    headers = {"Accept": "application/json",
               "User-Agent": "piko-cli"}

    tok = config.token() if auth else ""

    if tok:
        headers["Authorization"] = "Bearer" + tok
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
    if resp.status_code >= 400:
        raise Fail("Piko returned %s." % resp.status_code)

    try:
        body = resp.json()
    except ValueError:
        raise Fail("Piko sent back something unreadable")

    if not params:
        _save_cache(url, resp.headers.get("ETag") , body)
    return body

def whoami():
    return get("/me")

def tracks():
    return get("/tracks", auth=False)


def track(slug):
    return get("/tracks/%s" % slug, auth=False)

def problems(topic=None, difficulty=None, q=None, page=1, per_page=25):
    params = {"page": page, "per_page": per_page}
    if topic:
        params["topic"] = topic
    if difficulty:
        params["difficulty"] = difficulty
    if q:
        params["q"] = q
    return get("/problems", params=params, auth=False)


def problem(slug):
    return get("/problems/%s" % slug, auth=False)
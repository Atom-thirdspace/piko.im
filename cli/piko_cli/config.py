import json
import os
import stat
import time
from pathlib import Path



DEFAULT_API = "https://piko.aryan.my/api/v1"
HOME = Path(os.environ.get("PIKO_HOME") or (Path.home() / ".piko"))
CONFIG = HOME / "config.json"
CACHE = HOME / "cache"

def _read():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

def _write(data):
    HOME.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        CONFIG.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass            

def api_base():
    return (os.environ.get("PIKO_API")
            or _read().get("api")
            or DEFAULT_API).rstrip("/")

def token():
    return (os.environ.get("PIKO_TOKEN") or _read().get("token") or "").strip()

def save_token(value, api=None):
    data = _read()
    data["token"] = (value or "").strip()
    if api:
        data["api"] = api.rstrip("/")
    _write(data)

def masked(value=None):
    raw = value or token()
    if not raw:
        return "(none)"
    return raw[:12] + "…" + raw[-4:] if len(raw) > 20 else raw[:8] + "…"



def set_api(url):
    data = _read()
    data["api"] = url.rstrip("/")
    _write(data)


def site():
    """The web origin, for pages a browser visits rather than API calls."""
    return api_base().replace("/api/v1", "")


def save_oauth(access, refresh, expires_in, api=None):
    data = _read()
    data["token"] = (access or "").strip()
    data["refresh_token"] = (refresh or "").strip()
    data["expires_at"] = int(time.time()) + int(expires_in or 0)
    if api:
        data["api"] = api.rstrip("/")
    _write(data)


def oauth_state():
    data = _read()
    return data.get("refresh_token", ""), int(data.get("expires_at") or 0)


def clear_token():
    data = _read()
    for key in ("token", "refresh_token", "expires_at"):
        data.pop(key, None)
    _write(data)
    return bool(CONFIG.exists())

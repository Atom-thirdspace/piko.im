import json
import time

from . import config

CHECK_EVERY = 86400
URL = "https://pypi.org/pypi/piko-cli/json"

def current():
    try:
        from importlib.metadata import version
        return version("piko-cli")
    except Exception:
        return "0.0.0"

def _parts(text):
    out = []
    for chunk in (text or "0").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        out.append(int(digits or 0))
    return out

def newer_available():
    stamp = config.HOME / "version-check.json"
    try:
        saved = json.loads(stamp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}

    if time.time() - saved.get("at", 0) < CHECK_EVERY:
        latest = saved.get("latest") or ""
    else:
        try:
            import requests

            body = requests.get(URL, timeout=3).json()
            latest = body["info"]["version"]
        except Exception:
            latest = saved.get("latest") or ""
        try:
            config.HOME.mkdir(parents=True, exist_ok=True)
            stamp.write_text(json.dumps({"at": int(time.time()),
                                         "latest": latest}), encoding="utf-8")
        except OSError:
            pass

    if latest and _parts(latest) > _parts(current()):
        return latest
    return None

def upgrade_command():
    import sys
    return [sys.executable, "-m", "pip", "install", "--upgrade", "piko-cli"]

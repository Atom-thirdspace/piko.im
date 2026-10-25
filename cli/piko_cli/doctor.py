import os
import shutil
import subprocess
import sys
import time

from . import api, config, runner
from .output import Fail

OK, WARN, BAD = "ok", "warn", "bad"

def _first_line(cmd):
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except(OSError, subprocess.SubprocessError):
        return None
    text = (proc.stdout or proc.stderr or "").strip()
    return text.splitlines()[0] if text else None

def runtime_checks():
    out = [(OK if sys.version_info >= (3, 9) else BAD, "python",
            "%d.%d.%d  (%s)" % (sys.version_info[:3] + (sys.executable,)))]

    probes = (("cpp", ["g++", "--version"], "g++"),
              ("java", ["javac", "-version"], "javac"))
    for name, cmd, binary in probes:
        if not shutil.which(binary):
            out.append((WARN, name,
                        "%s not on PATH - `--lang %s` won't run locally"
                        % (binary, name)))
            continue
        out.append((OK, name, _first_line(cmd) or "found"))
    return out

def piko_checks():
    out = []
    base = config.api_base()
    started = time.time()
    try:
        body = api.get("/health", auth=False, use_cache=True)
    except Fail as exc:
        out.append((BAD, "api", "%s  %s" % (base, exc)))
        return out
    ms = int((time.time() - started) * 1000)
    out.append((OK if body.get("status") == "ok" else BAD, "api",
                "%s  %d ms" % (base, ms)))
    if ms > 1500:
        out.append((WARN, "", "that is slow - every command pays it"))

    if not config.token():
        out.append((WARN, "auth", "not signed in - run `piko login`"))
        return out

    try:
        who = api.whoami()
    except Fail as exc:
        out.append((BAD, "auth", str(exc)))
        return out

    scopes = (who.get("key") or {}).get("scopes") or []
    out.append((OK, "auth", "%s  (%s)" % (who.get("username") or "?",
                                          config.masked())))
    want = ("submissions:write", "progress:read", "notifications:read")
    missing = [s for s in want if s not in scopes]
    out.append((WARN if missing else OK, "scopes",
                ", ".join(scopes) or "none"))
    if missing:
        out.append((WARN, "", "missing %s - sign in again to pick them up"
                    % ", ".join(missing)))

    _, expires_at = config.oauth_state()
    if expires_at:
        left = int(expires_at - time.time())
        out.append((OK, "token", "valid %dm more" % (left // 60) if left > 0
                    else "expired - the next command refreshes it"))
    return out

def terminal_checks():
    size = shutil.get_terminal_size((0, 0))
    tty = sys.stdout.isatty()
    out = [(OK if tty else WARN, "tty",
            "%dx%d" % (size.columns, size.lines) if tty
            else "not a terminal - `piko ui` is unavailable")]

    if os.name == "nt":
        from .tui.screen import _enable_vt
        live = _enable_vt()
        out.append((OK if live else BAD, "ansi",
                    "virtual terminal on" if live
                    else "this console can't do ANSI - colours and the TUI "
                         "will look wrong"))
    if tty and (size.columns < 50 or size.lines < 8):
        out.append((WARN, "size", "`piko ui` wants at least 50x8"))
    if os.environ.get("NO_COLOR"):
        out.append((OK, "colour", "off (NO_COLOR is set)"))
    return out

def local_checks():
    from . import workspace

    root = workspace.find()
    files = list(config.CACHE.glob("*.json")) if config.CACHE.is_dir() else []
    size = sum(f.stat().st_size for f in files)
    return [
        (OK if config.CONFIG.exists() else WARN, "config",
         str(config.CONFIG) if config.CONFIG.exists() else "not written yet"),
        (OK if root else WARN, "workspace",
         str(root) if root else "none here - `piko init` makes one"),
        (OK, "cache", "%d entries, %.1f KB" % (len(files), size / 1024.0)),
    ]

def run_all():
    return [("Runtime", runtime_checks()),
            ("Piko", piko_checks()),
            ("Terminal", terminal_checks()),
            ("Local", local_checks())]
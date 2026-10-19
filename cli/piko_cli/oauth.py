"""Browser sign-in for the CLI: PKCE over a loopback redirect.

The verifier never leaves this process and the code arrives on a socket
bound to 127.0.0.1, so nothing travelling through the browser's URL bar is
worth anything on its own.
"""

import base64
import hashlib
import http.server
import secrets
import threading
import time
import urllib.parse
import webbrowser

from .output import Fail

LOOPBACK_TIMEOUT = 300
PAGE = """<!doctype html><meta charset="utf-8">
<title>Piko CLI</title>
<style>body{font:16px system-ui;margin:4rem auto;max-width:28rem;color:#2b2b2b}
h1{font-size:1.2rem}</style>
<h1>%s</h1><p>%s</p>"""


def _b64(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def make_pkce():
    verifier = _b64(secrets.token_bytes(48))
    challenge = _b64(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


class _Catcher(http.server.BaseHTTPRequestHandler):
    result = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_error(404)
            return
        query = urllib.parse.parse_qs(parsed.query)
        type(self).result = {k: v[0] for k, v in query.items()}

        failed = "error" in type(self).result
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        body = PAGE % (
            ("That sign-in was cancelled.", "Nothing was shared.")
            if failed else
            ("You're signed in.",
             "Close this tab and go back to your terminal."))
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, *args):
        pass                      # the CLI prints its own progress


def listen():
    """A socket on a free loopback port, bound before we ask for a code."""
    _Catcher.result = None
    server = http.server.HTTPServer(("127.0.0.1", 0), _Catcher)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_port


def wait_for_code(server, state, timeout=LOOPBACK_TIMEOUT):
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            got = _Catcher.result
            if got is not None:
                if got.get("error"):
                    raise Fail("Piko said: %s" % (got.get("error_description")
                                                  or got["error"]))
                if got.get("state") != state:
                    raise Fail("The browser sent back a mismatched state. "
                               "Start again.")
                if not got.get("code"):
                    raise Fail("The browser did not send a code back.")
                return got["code"]
            time.sleep(0.2)
    finally:
        server.shutdown()
        server.server_close()
    raise Fail("Timed out waiting for the browser.")


def open_browser(url):
    try:
        return webbrowser.open(url)
    except Exception:
        return False

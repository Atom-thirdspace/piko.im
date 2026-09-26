import hmac
import secrets
from flask import abort, current_app, request, session
from markupsafe import Markup

FIELD = "_csrf"
HEADER = "X-CSRF-Token"
SESSION_KEY = "csrf_token"
UNSAFE = ("POST", "PUT", "PATCH", "DELETE")

def token():
    if SESSION_KEY not in session:
        session[SESSION_KEY] = secrets.token_urlsafe(32)
    return session[SESSION_KEY]

def field():
    return Markup('<input type="hidden" name="%s" value="%s">' % (FIELD, token()))

def exempt(view):
    view.csrf_exempt = True
    return view

def init_csrf(app):
    app.jinja_env.globals["csrf_token"] = token
    app.jinja_env.globals["csrf_field"] = field

    @app.before_request
    def _guard():
        if request.method not in UNSAFE:
            return
        view = app.view_functions.get(request.endpoint)
        if view is not None and getattr(view, "csrf_exempt", False):
            return

        sent = request.form.get(FIELD) or request.headers.get(HEADER) or ""
        expected = session.get(SESSION_KEY) or ""
        if not expected or not hmac.compare_digest(sent, expected):
            current_app.logger.warning("CSRF reject on %s", request.endpoint)
            abort(400, description="Your session expired. Reload and try again.")

            
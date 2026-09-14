from functools import wraps
from flask import g, redirect, request, session, url_for

def current_user():
    if "user" not in g:
        uid = session.get("user_id")
        g.user = load_user(uid) if uid else None
    return g.user

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for("auth.login_page", next=request.full_path))
        return view(*args, **kwargs)
    return wrapped
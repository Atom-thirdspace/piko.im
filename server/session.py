from functools import wraps
from flask import g, redirect, request, session, url_for
from urllib.parse import urlparse, urljoin

from .models import load_user

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

def is_safe_next(target):
    if not target:
        return False
    ref = urlparse(request.host_url)
    test = urlparse(urljoin(request.host_url, target))
    return test.scheme in ("http", "https") and ref.netloc == test.netloc

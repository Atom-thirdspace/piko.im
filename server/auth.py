import os
import secrets
from urllib.parse import urlparse, urljoin

from flask import (
    Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
)
from .oauth import oauth, init_oauth
from .profile import fetch_profile

auth_bp = Blueprint("auth", __name__)

def _is_safe_next(target):
    if not target:
        return False
    ref = urlparse(request.host_url)
    test = urlparse(urljoin(request.host_url, target))
    return test.scheme in ("http", "https") and ref.netloc == test.netloc

@auth_bp.route("/login/")
def login_page():
    enabled = current_app.config.get("ENABLED_PROVIDERS", [])
    from flask import render_template
    return render_template("login.html", enabled=enabled)
    
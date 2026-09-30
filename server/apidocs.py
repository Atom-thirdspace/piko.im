"""The developer-facing documentation page for the public API."""

from flask import Blueprint, render_template

from .models import API_SCOPES
from .publicapi import (DEFAULT_PER_PAGE, MAX_PER_PAGE, RATE_WINDOW, TIER_ANON,
                        TIER_KEY, TIER_PRO, VERSION)

docs_bp = Blueprint("apidocs", __name__)


@docs_bp.route("/developers/")
def index():
    return render_template(
        "developers.html",
        version=VERSION,
        scopes=API_SCOPES,
        window=RATE_WINDOW,
        tiers=[("No key", TIER_ANON, "Catalog endpoints only."),
               ("With a key", TIER_KEY, "Adds everything under /me."),
               ("With Piko Pro", TIER_PRO, "Same endpoints, higher ceiling.")],
        default_per_page=DEFAULT_PER_PAGE,
        max_per_page=MAX_PER_PAGE,
    )

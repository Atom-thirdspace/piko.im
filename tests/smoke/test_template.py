from collections import Counter

import pytest


def test_app_imports():
    import app  # noqa: F401


def test_routes_register(flask_app):
    rules = list(flask_app.url_map.iter_rules())
    assert len(rules) > 100, "far fewer routes than expected"


def test_no_duplicate_endpoints(flask_app):
    names = [r.endpoint.rsplit(".", 1)[-1]
             for r in flask_app.url_map.iter_rules()]
    suspicious = [n for n, count in Counter(names).items()
                  if n in ("inner", "wrapped", "wrapper", "decorated")]
    assert suspicious == [], (
        "views registered under a decorator's name: %s - a decorator is "
        "missing @wraps(view)" % suspicious)


def test_every_view_is_callable(flask_app):
    for endpoint, view in flask_app.view_functions.items():
        assert callable(view), endpoint


@pytest.mark.parametrize("name", [
    "publicapi", "problems", "playground", "auth", "oauth", "dashboard",
    "admin", "apidocs", "health",
])
def test_core_blueprints_present(flask_app, name):
    assert name in flask_app.blueprints


def test_public_endpoints_resolve(flask_app):
    from flask import url_for

    with flask_app.test_request_context():
        for endpoint in ("problems.index", "playground.index",
                         "apidocs.index", "leaderboard.index",
                         "blog.index", "billing.pricing"):
            assert url_for(endpoint)

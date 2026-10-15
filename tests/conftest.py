import sys
import time

import pytest

sys.path.insert(0, "E:/piko.im")

import app as appmod
from flask import g
from server.models import db


@pytest.fixture(scope="session")
def app():
    appmod.app.config["TESTING"] = True
    return appmod.app


@pytest.fixture
def ctx(app):
    with app.app_context():
        yield


@pytest.fixture
def session(app):
    with app.app_context():
        connection = db.engine.connect()
        transaction = connection.begin()
        db.session.configure(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield db.session
        finally:
            db.session.remove()
            transaction.rollback()
            connection.close()
            db.session.configure(bind=db.engine)


@pytest.fixture
def clear_g():
    def _clear():
        for key in list(g.__dict__.keys()):
            g.__dict__.pop(key, None)
    return _clear


@pytest.fixture
def client(app, clear_g):
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["csrf_token"] = "test-token"
    c.csrf = "test-token"
    clear_g()
    return c


@pytest.fixture
def as_user(client, clear_g):
    def _login(user):
        with client.session_transaction() as sess:
            sess["user_id"] = user.id
            sess["csrf_token"] = "test-token"
        clear_g()
        return client
    return _login


@pytest.fixture
def as_admin(as_user, clear_g):
    def _login(user):
        c = as_user(user)
        with c.session_transaction() as sess:
            sess["admin_unlock"] = {"uid": user.id, "at": time.time()}
        clear_g()
        return c
    return _login


@pytest.fixture
def no_mail(monkeypatch):
    sent = []
    monkeypatch.setattr("server.mailer._send",
                        lambda *a, **k: (sent.append((a, k)) or True))
    return sent

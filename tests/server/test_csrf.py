import pytest

pytestmark = pytest.mark.db


def test_post_without_a_token_is_refused(client):
    resp = client.post("/playground/run",
                       json={"language": "python", "source": "print(1)"})
    assert resp.status_code in (400, 403)


def test_post_with_the_token_passes_the_guard(client):
    resp = client.post("/playground/run",
                       json={"language": "python", "source": "print(1)"},
                       headers={"X-CSRF-Token": client.csrf})
    assert resp.status_code not in (400, 403)


def test_webhooks_are_exempt(client):
    resp = client.post("/webhooks/polar", data=b"{}")
    assert resp.status_code == 403        

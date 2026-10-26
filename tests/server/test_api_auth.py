import pytest

pytestmark = pytest.mark.db

PRIVATE = [
    "/api/v1/me",
    "/api/v1/me/submissions",
    "/api/v1/me/stats",
    "/api/v1/me/mastery",
    "/api/v1/me/coins",
    "/api/v1/me/achievements",
    "/api/v1/me/notifications",
    "/api/v1/me/next",
    "/api/v1/me/streak",
]

PUBLIC = [
    "/api/v1/",
    "/api/v1/health",
    "/api/v1/problems",
    "/api/v1/tracks",
    "/api/v1/topics",
    "/api/v1/languages",
]

ADMIN = [
    "/api/v1/admin/stats",
    "/api/v1/admin/traffic",
    "/api/v1/admin/users",
    "/api/v1/admin/audit",
]


@pytest.mark.parametrize("path", PRIVATE)
def test_private_endpoints_need_a_key(client, path):
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", PUBLIC)
def test_public_endpoints_are_public(client, path):
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("path", ADMIN)
def test_admin_endpoints_deny_anonymous(client, path):
    assert client.get(path).status_code in (401, 404)


def test_bad_bearer_token_is_rejected(client):
    resp = client.get("/api/v1/me",
                      headers={"Authorization": "Bearer piko_sk_nope"})
    assert resp.status_code == 401


def test_submission_create_needs_a_key(client):
    resp = client.post("/api/v1/submissions",
                       json={"problem": "x", "language": "python",
                             "source": "print(1)"})
    assert resp.status_code == 401

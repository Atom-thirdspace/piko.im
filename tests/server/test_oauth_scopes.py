import pytest

pytestmark = pytest.mark.db


def test_client_cannot_exceed_its_max_scopes(ctx):
    from server.models import OAuthClient
    from server.oauthserver import parse_scopes

    client = OAuthClient(client_id="t", name="t", first_party=True,
                         max_scopes=["catalog:read"])
    with pytest.raises(ValueError):
        parse_scopes(client, "catalog:read me:read")


def test_unknown_scope_is_rejected(ctx):
    from server.models import OAuthClient
    from server.oauthserver import parse_scopes

    client = OAuthClient(client_id="t", name="t", first_party=True,
                         max_scopes=["catalog:read", "invented:scope"])
    with pytest.raises(ValueError):
        parse_scopes(client, "invented:scope")


def test_write_scopes_need_a_trusted_client(ctx):
    from server.models import OAuthClient
    from server.oauthserver import parse_scopes

    stranger = OAuthClient(client_id="t", name="t", first_party=False,
                           verified_at=None,
                           max_scopes=["submissions:write"])
    with pytest.raises(ValueError):
        parse_scopes(stranger, "submissions:write")


def test_the_cli_client_can_ask_for_what_the_cli_asks_for(ctx):
    from server.oauthserver import _find_client, parse_scopes

    client = _find_client("piko-cli")
    if client is None:
        pytest.skip("piko-cli is not seeded in this database")

    from piko_cli.cli import SCOPES

    assert parse_scopes(client, " ".join(SCOPES))


def test_loopback_redirect_ignores_the_port(ctx):
    from server.models import OAuthClient
    from server.oauthserver import redirect_allowed

    client = OAuthClient(client_id="t", name="t", first_party=True,
                         redirect_uris=["http://127.0.0.1/callback"])
    assert redirect_allowed(client, "http://127.0.0.1:53129/callback")
    assert not redirect_allowed(client, "http://evil.test/callback")
    assert not redirect_allowed(client, "http://127.0.0.1:53129/other")

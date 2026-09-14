import os
from authlib.integrations.flask_client import OAuth

oauth = OAuth()

PROVIDERS = {
    "google": {
        "label": "Google",
        "register": {
            "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
            "client_kwargs": {"scope": "openid email profile"},
        },
    },
    "github": {
        "label": "GitHub",
        "register": {
            "api_base_url": "https://api.github.com/",
            "access_token_url": "https://github.com/login/oauth/access_token",
            "authorize_url": "https://github.com/login/oauth/authorize",
            "client_kwargs": {"scope": "read:user user:email"},
        },
    },
    "discord": {
        "label": "Discord",
        "register": {
            "api_base_url": "https://discord.com/api/",
            "access_token_url": "https://discord.com/api/oauth2/token",
            "authorize_url": "https://discord.com/oauth2/authorize",
            "client_kwargs": {"scope": "identify email"},
        },
    },
}


def init_oauth(app):
    """Register every provider that has both env credentials set."""
    oauth.init_app(app)
    enabled = []
    for name, cfg in PROVIDERS.items():
        client_id = os.environ.get(f"{name.upper()}_CLIENT_ID")
        client_secret = os.environ.get(f"{name.upper()}_CLIENT_SECRET")
        if not (client_id and client_secret):
            continue
        oauth.register(
            name=name,
            client_id=client_id,
            client_secret=client_secret,
            **cfg["register"],
        )
        enabled.append(name)
    app.config["ENABLED_PROVIDERS"] = enabled
    return enabled

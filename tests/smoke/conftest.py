import os

os.environ.setdefault("DATABASE_URL",
                      "postgresql+psycopg://u:p@127.0.0.1:1/none")
os.environ.setdefault("SECRET_KEY", "test-only")
os.environ.setdefault("PIKO_ENV", "test")
os.environ.setdefault("PIKO_TRAFFIC", "off")

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def flask_app():
    import app as appmod

    appmod.app.config["TESTING"] = True
    return appmod.app

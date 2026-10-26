import pytest

pytestmark = pytest.mark.db

def test_no_schema_drift(ctx):
    from server.health import schema_drift

    drift = schema_drift()
    assert drift["ok"], (
        "run the pending migrations in scripts/\n  missing tables: %s\n"
        "  missing columns: %s"
        % (drift["missing_tables"], drift["missing_columns"]))


def test_database_answers(ctx):
    from server.health import _db_probe

    assert _db_probe()["ok"]
    
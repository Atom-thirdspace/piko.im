"""Run a .sql file against DATABASE_URL. Usage: python scripts/run_migration.py <file.sql>"""
import sys

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

sys.path.insert(0, ".")
from server.models import _normalize_db_url      # noqa: E402

import os                                        # noqa: E402

load_dotenv()

sql_path = sys.argv[1]
url = os.environ["DATABASE_URL"]
engine = create_engine(_normalize_db_url(url))

with open(sql_path, encoding="utf-8") as handle:
    script = handle.read()

def _strip_comments(chunk):
    return "\n".join(line for line in chunk.splitlines()
                     if not line.lstrip().startswith("--")).strip()


with engine.begin() as conn:
    for chunk in script.split(";"):
        statement = _strip_comments(chunk)
        if not statement:
            continue
        print(">>", " ".join(statement.split())[:90])
        conn.execute(text(statement))

print("done")

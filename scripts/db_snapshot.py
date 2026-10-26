import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv 

load_dotenv()

def plain_url(url):
    return (url or "").replace("postgresql+psycopg://", "postgresql://") \
                      .replace("postgres://", "postgresql://")


def dump(url, out_path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["pg_dump", "--format=custom", "--no-owner", "--no-privileges",
           "--file", str(out_path), plain_url(url)]
    started = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit("pg_dump failed:\n" + (proc.stderr or proc.stdout))
    size = out_path.stat().st_size
    print("dumped %.1f MB in %.1fs -> %s"
          % (size / 1048576.0, time.time() - started, out_path))
    return out_path

def restore(path, target_url):
    cmd = ["pg_restore", "--no-owner", "--no-privileges", "--clean",
           "--if-exists", "--dbname", plain_url(target_url), str(path)]
    started = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 and "error:" in (proc.stderr or "").lower():
        raise SystemExit("pg_restore failed:\n" + proc.stderr)
    print("restored in %.1fs" % (time.time() - started))

def verify(target_url):
    from sqlalchemy import create_engine, text

    engine = create_engine(plain_url(target_url))
    with engine.connect() as conn:
        rows = conn.execute(text(
            "select 'users', count(*) from users "
            "union all select 'problems', count(*) from problems "
            "union all select 'submissions', count(*) from submissions "
            "union all select 'lessons', count(*) from lessons")).all()
    for name, count in rows:
        print("  %-12s %s" % (name, count))
    return dict(rows)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="backups/piko.dump")
    parser.add_argument("--restore-into", metavar="URL",
                        help="a scratch database to prove the dump restores")
    args = parser.parse_args()

    source = os.environ.get("DATABASE_URL")
    if not source:
        raise SystemExit("DATABASE_URL is not set")

    path = dump(source, Path(args.out))

    if args.restore_into:
        if args.restore_into == source:
            raise SystemExit("refusing to restore over the source database")
        print("restoring into the scratch database...")
        restore(path, args.restore_into)
        print("row counts in the restored copy:")
        verify(args.restore_into)
    else:
        print("no --restore-into given, so this dump is untested")

if __name__ == "__main__":
    main()

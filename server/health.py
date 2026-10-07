import time
from datetime import timedelta

from flask import Blueprint, jsonify
from sqlalchemy import text

from .admin_gate import admin_required
from .models import JudgeJob, _utcnow, db

health_bp = Blueprint("health", __name__)

# A job sitting unclaimed longer than this means nothing is draining the
# queue - almost always a dead `flask judge-worker`.
WORKER_STALL_MINUTES = 5
SLOW_DB_MS = 250


def _db_probe():
    """Round-trip latency to the database, which is the dominant cost."""
    start = time.perf_counter()
    try:
        db.session.execute(text("SELECT 1"))
        ms = (time.perf_counter() - start) * 1000
        return {"ok": True, "latency_ms": round(ms, 1), "slow": ms > SLOW_DB_MS}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}


def schema_drift():
    """Tables and columns the models expect but the database does not have.

    One query against information_schema rather than SQLAlchemy's inspector,
    which asks per table - 47 round trips is over two minutes on the sort of
    slow link this page exists to diagnose.
    """
    rows = db.session.execute(text(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema()"
    )).all()

    live = {}
    for table_name, column_name in rows:
        live.setdefault(table_name, set()).add(column_name)

    missing_tables, missing_columns = [], []
    for name, table in db.metadata.tables.items():
        if name not in live:
            missing_tables.append(name)
            continue
        for column in table.columns:
            if column.name not in live[name]:
                missing_columns.append("%s.%s" % (name, column.name))

    return {"ok": not (missing_tables or missing_columns),
            "missing_tables": sorted(missing_tables),
            "missing_columns": sorted(missing_columns)}


def judge_state():
    now = _utcnow()
    stall_before = now - timedelta(minutes=WORKER_STALL_MINUTES)

    def count(*where):
        return db.session.execute(
            db.select(db.func.count()).select_from(JudgeJob).where(*where)
        ).scalar() or 0

    queued = count(JudgeJob.status == "queued")
    stalled = count(JudgeJob.status == "queued",
                    JudgeJob.created_at < stall_before)
    last_done = db.session.execute(
        db.select(db.func.max(JudgeJob.finished_at))
        .where(JudgeJob.status == "done")).scalar()

    return {
        # Nothing queued is healthy whether or not a worker is alive; a
        # backlog that is not moving is not.
        "ok": stalled == 0,
        "queued": queued,
        "stalled": stalled,
        "running": count(JudgeJob.status == "running"),
        "failed": count(JudgeJob.status == "failed"),
        "last_finished": last_done.isoformat() if last_done else None,
    }


@health_bp.route("/healthz")
def healthz():
    """Liveness. Deliberately thin - monitors poll this often."""
    probe = _db_probe()
    body = {"status": "ok" if probe["ok"] else "down", "db": probe["ok"]}
    return jsonify(body), (200 if probe["ok"] else 503)


@health_bp.route("/admin/health/")
@admin_required
def detail():
    probe = _db_probe()
    schema = schema_drift() if probe["ok"] else {"ok": False, "unknown": True}
    judge = judge_state() if probe["ok"] else {"ok": False, "unknown": True}

    healthy = probe["ok"] and schema["ok"] and judge["ok"]
    return jsonify({
        "status": "ok" if healthy else "degraded",
        "db": probe,
        "schema": schema,
        "judge": judge,
    }), (200 if healthy else 503)

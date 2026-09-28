-- Run-button executions. Separate from submissions: a run is not an attempt,
-- earns no XP and never sets a verdict on the problem.
CREATE TABLE IF NOT EXISTS scratch_runs (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    problem_id      INTEGER REFERENCES problems(id) ON DELETE CASCADE,
    language        VARCHAR(16) NOT NULL,
    source          TEXT NOT NULL,
    stdin           TEXT NOT NULL DEFAULT '',
    status          VARCHAR(16) NOT NULL DEFAULT 'queued',
    verdict         VARCHAR(32) NOT NULL DEFAULT '',
    stdout          TEXT NOT NULL DEFAULT '',
    stderr          TEXT NOT NULL DEFAULT '',
    compile_output  TEXT NOT NULL DEFAULT '',
    time_ms         INTEGER NOT NULL DEFAULT 0,
    error           TEXT NOT NULL DEFAULT '',
    attempts        INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    claimed_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_scratch_runs_user_id    ON scratch_runs (user_id);
CREATE INDEX IF NOT EXISTS ix_scratch_runs_problem_id ON scratch_runs (problem_id);
CREATE INDEX IF NOT EXISTS ix_scratch_runs_status     ON scratch_runs (status);
CREATE INDEX IF NOT EXISTS ix_scratch_runs_created_at ON scratch_runs (created_at);

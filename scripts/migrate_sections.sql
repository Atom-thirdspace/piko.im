-- Trust & safety
CREATE TABLE IF NOT EXISTS reports (
    id           serial PRIMARY KEY,
    reporter_id  integer REFERENCES users(id) ON DELETE SET NULL,
    kind         varchar(16) NOT NULL,          -- user | team | solution
    target_id    integer NOT NULL,
    reason       varchar(32) NOT NULL,
    detail       text NOT NULL DEFAULT '',
    status       varchar(16) NOT NULL DEFAULT 'open',   -- open | actioned | dismissed
    handled_by   integer REFERENCES users(id) ON DELETE SET NULL,
    handled_note text NOT NULL DEFAULT '',
    created_at   timestamptz NOT NULL DEFAULT now(),
    handled_at   timestamptz
);
CREATE INDEX IF NOT EXISTS ix_reports_open ON reports (created_at DESC)
    WHERE status = 'open';
CREATE UNIQUE INDEX IF NOT EXISTS uq_report_once
    ON reports (reporter_id, kind, target_id) WHERE status = 'open';

ALTER TABLE users ADD COLUMN IF NOT EXISTS is_suspended boolean NOT NULL DEFAULT false;

-- Judge queue
CREATE TABLE IF NOT EXISTS judge_jobs (
    id            serial PRIMARY KEY,
    submission_id integer NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
    status        varchar(16) NOT NULL DEFAULT 'queued',  -- queued|running|done|failed
    attempts      integer NOT NULL DEFAULT 0,
    error         text NOT NULL DEFAULT '',
    created_at    timestamptz NOT NULL DEFAULT now(),
    claimed_at    timestamptz,
    finished_at   timestamptz
);
CREATE INDEX IF NOT EXISTS ix_judge_jobs_queued ON judge_jobs (created_at)
    WHERE status = 'queued';

-- Caching + community solutions
ALTER TABLE submissions ADD COLUMN IF NOT EXISTS tests_hash varchar(64) NOT NULL DEFAULT '';
ALTER TABLE submissions ADD COLUMN IF NOT EXISTS source_hash varchar(64) NOT NULL DEFAULT '';
ALTER TABLE submissions ADD COLUMN IF NOT EXISTS is_public boolean NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS ix_sub_cache
    ON submissions (user_id, problem_id, language, source_hash, tests_hash);
CREATE INDEX IF NOT EXISTS ix_sub_public ON submissions (problem_id, created_at DESC)
    WHERE is_public AND verdict = 'accepted';

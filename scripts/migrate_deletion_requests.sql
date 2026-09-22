CREATE TABLE IF NOT EXISTS deletion_requests (
    id            serial PRIMARY KEY,
    user_id       integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reason        varchar(32) NOT NULL,
    detail        text NOT NULL DEFAULT '',
    status        varchar(16) NOT NULL DEFAULT 'pending',
    created_at    timestamptz NOT NULL DEFAULT now(),
    decided_at    timestamptz,
    decided_by_id integer REFERENCES users(id) ON DELETE SET NULL,
    decision_note text NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS ix_deletion_requests_user_id ON deletion_requests (user_id);
CREATE INDEX IF NOT EXISTS ix_deletion_requests_status  ON deletion_requests (status);

CREATE UNIQUE INDEX IF NOT EXISTS uq_deletion_pending
    ON deletion_requests (user_id) WHERE status = 'pending';
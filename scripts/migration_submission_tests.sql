CREATE TABLE IF NOT EXISTS submission_tests (
    id            serial PRIMARY KEY,
    submission_id integer NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
    position      integer NOT NULL,
    verdict       varchar(32) NOT NULL,
    time_ms       integer NOT NULL DEFAULT 0,
    is_sample     boolean NOT NULL DEFAULT false,
    stdout        text NOT NULL DEFAULT '',
    stderr        text NOT NULL DEFAULT '',
    CONSTRAINT uq_submission_test UNIQUE (submission_id, position)
);

CREATE INDEX IF NOT EXISTS ix_submission_tests_sub ON submission_tests (submission_id);

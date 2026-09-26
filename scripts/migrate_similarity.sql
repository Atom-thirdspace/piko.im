CREATE TABLE IF NOT EXISTS submission_fingerprints (
    submission_id integer NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
    problem_id    integer NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
    hash          bigint NOT NULL,
    PRIMARY KEY (submission_id, hash)
);
-- The whole detection query is "who else has these hashes on this problem".
CREATE INDEX IF NOT EXISTS ix_fp_lookup ON submission_fingerprints (problem_id, hash);

CREATE TABLE IF NOT EXISTS similarity_flags (
    id            serial PRIMARY KEY,
    submission_id integer NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
    matched_id    integer NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
    score         real NOT NULL,
    status        varchar(16) NOT NULL DEFAULT 'open',
    created_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_sim_pair UNIQUE (submission_id, matched_id),
    CONSTRAINT ck_sim_not_self CHECK (submission_id <> matched_id)
);
CREATE INDEX IF NOT EXISTS ix_sim_open ON similarity_flags (created_at DESC)
    WHERE status = 'open';

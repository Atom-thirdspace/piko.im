CREATE TABLE IF NOT EXISTS generated_problems (
    id           serial PRIMARY KEY,
    source       varchar(64) NOT NULL,        -- template:<name> | llm
    slug         varchar(80) NOT NULL,
    title        varchar(200) NOT NULL,
    topic        varchar(64) NOT NULL,
    difficulty   varchar(16) NOT NULL,
    xp           integer NOT NULL DEFAULT 15,
    statement_md text NOT NULL,
    payload      jsonb NOT NULL,              -- tests, hints, reference solution
    status       varchar(16) NOT NULL DEFAULT 'draft',  -- draft|approved|rejected
    note         text NOT NULL DEFAULT '',
    created_at   timestamptz NOT NULL DEFAULT now(),
    reviewed_by  integer REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at  timestamptz,
    CONSTRAINT uq_generated_slug UNIQUE (slug)
);
CREATE INDEX IF NOT EXISTS ix_generated_draft ON generated_problems (created_at DESC)
    WHERE status = 'draft';

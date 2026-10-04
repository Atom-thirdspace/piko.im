CREATE TABLE IF NOT EXISTS contests (
    id              SERIAL PRIMARY KEY,
    slug            VARCHAR(64) NOT NULL UNIQUE,
    title           VARCHAR(200) NOT NULL,
    description_md  TEXT NOT NULL DEFAULT '',
    starts_at       TIMESTAMPTZ NOT NULL,
    ends_at         TIMESTAMPTZ NOT NULL,
    freeze_minutes  INTEGER NOT NULL DEFAULT 30,
    published       BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by_id   INTEGER REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_contests_slug ON contests (slug);

CREATE TABLE IF NOT EXISTS contest_problems (
    id          SERIAL PRIMARY KEY,
    contest_id  INTEGER NOT NULL REFERENCES contests(id) ON DELETE CASCADE,
    problem_id  INTEGER NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT uq_contest_problem UNIQUE (contest_id, problem_id)
);
CREATE INDEX IF NOT EXISTS ix_contest_problems_contest_id ON contest_problems (contest_id);
CREATE INDEX IF NOT EXISTS ix_contest_problems_problem_id ON contest_problems (problem_id);

CREATE TABLE IF NOT EXISTS contest_entries (
    id          SERIAL PRIMARY KEY,
    contest_id  INTEGER NOT NULL REFERENCES contests(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    joined_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_contest_entry UNIQUE (contest_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_contest_entries_contest_id ON contest_entries (contest_id);
CREATE INDEX IF NOT EXISTS ix_contest_entries_user_id ON contest_entries (user_id);

CREATE TABLE IF NOT EXISTS notifications (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind        VARCHAR(32) NOT NULL,
    ref         VARCHAR(64) NOT NULL DEFAULT '',
    title       VARCHAR(200) NOT NULL,
    body        TEXT NOT NULL DEFAULT '',
    url         VARCHAR(300) NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    read_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_notifications_user_id ON notifications (user_id);
CREATE INDEX IF NOT EXISTS ix_notifications_created_at ON notifications (created_at);

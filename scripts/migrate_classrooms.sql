CREATE TABLE IF NOT EXISTS classrooms (
    id            SERIAL PRIMARY KEY,
    owner_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name          VARCHAR(120) NOT NULL DEFAULT '',
    institution   VARCHAR(160) NOT NULL DEFAULT '',
    -- Short, unambiguous, and rotatable. Students type this.
    join_code     VARCHAR(16) NOT NULL UNIQUE,
    seats         INTEGER NOT NULL DEFAULT 0,
    source        VARCHAR(16) NOT NULL DEFAULT 'polar',
    polar_subscription_id VARCHAR(64) UNIQUE,
    note          TEXT NOT NULL DEFAULT '',
    granted_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    expires_at    TIMESTAMPTZ,
    archived_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_classrooms_owner  ON classrooms (owner_id);
CREATE INDEX IF NOT EXISTS ix_classrooms_code   ON classrooms (join_code);
CREATE INDEX IF NOT EXISTS ix_classrooms_source ON classrooms (source);

CREATE TABLE IF NOT EXISTS classroom_members (
    id           SERIAL PRIMARY KEY,
    classroom_id INTEGER NOT NULL REFERENCES classrooms(id) ON DELETE CASCADE,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    joined_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    removed_at   TIMESTAMPTZ,
    UNIQUE (classroom_id, user_id)
);

CREATE INDEX IF NOT EXISTS ix_members_user  ON classroom_members (user_id);
CREATE INDEX IF NOT EXISTS ix_members_class ON classroom_members (classroom_id);

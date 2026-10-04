-- In-app notifications. init_db runs create_all, which makes new TABLES on
-- its own, so this exists for production parity and for a reviewer reading
-- the migration history.
-- Keep semicolons out of these comments - the runner splits on them first.

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

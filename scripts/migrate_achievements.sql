CREATE TABLE IF NOT EXISTS user_achievements (
    id        serial PRIMARY KEY,
    user_id   integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key       varchar(48) NOT NULL,
    earned_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_user_achievement UNIQUE (user_id, key)
);
CREATE INDEX IF NOT EXISTS ix_achievements_user
    ON user_achievements (user_id, earned_at DESC);

CREATE INDEX IF NOT EXISTS ix_xp_user_time ON xp_events (user_id, created_at DESC);

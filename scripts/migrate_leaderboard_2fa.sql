-- Leaderboard
ALTER TABLE users ADD COLUMN IF NOT EXISTS show_on_leaderboard boolean NOT NULL DEFAULT true;

CREATE INDEX IF NOT EXISTS ix_users_board_xp     ON users (xp_total DESC)
    WHERE username IS NOT NULL AND show_on_leaderboard;
CREATE INDEX IF NOT EXISTS ix_users_board_streak ON users (streak_days DESC)
    WHERE username IS NOT NULL AND show_on_leaderboard;
CREATE INDEX IF NOT EXISTS ix_xp_events_created  ON xp_events (created_at DESC);

-- Two-factor
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_secret       text;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_confirmed_at timestamptz;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_last_step    bigint;
ALTER TABLE users ADD COLUMN IF NOT EXISTS backup_codes      text[] NOT NULL DEFAULT '{}';

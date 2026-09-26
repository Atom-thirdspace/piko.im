ALTER TABLE users ADD COLUMN IF NOT EXISTS streak_freezes integer NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS freezes_granted_on date;

CREATE TABLE IF NOT EXISTS streak_freeze_uses (
    id           serial PRIMARY KEY,
    user_id      integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    covered_date date NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_freeze_day UNIQUE (user_id, covered_date)
);

CREATE INDEX IF NOT EXISTS ix_freeze_user ON streak_freeze_uses (user_id, covered_date DESC)
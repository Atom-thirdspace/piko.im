ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS amount INTEGER NOT NULL DEFAULT 0;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS currency VARCHAR(8) NOT NULL DEFAULT 'usd';
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS recurring_interval VARCHAR(16) NOT NULL DEFAULT 'month';
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS recurring_interval_count INTEGER NOT NULL DEFAULT 1;

ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS source VARCHAR(16) NOT NULL DEFAULT 'polar';
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS note TEXT NOT NULL DEFAULT '';
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS granted_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_subscriptions_source     ON subscriptions (source);
CREATE INDEX IF NOT EXISTS ix_subscriptions_created_at ON subscriptions (created_at);
CREATE INDEX IF NOT EXISTS ix_subscriptions_ended      ON subscriptions (ends_at);

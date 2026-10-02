-- Paid seats on the existing social teams, plus student verification.

ALTER TABLE teams ADD COLUMN IF NOT EXISTS seats INTEGER NOT NULL DEFAULT 0;
ALTER TABLE teams ADD COLUMN IF NOT EXISTS licence_source VARCHAR(16) NOT NULL DEFAULT 'none';
ALTER TABLE teams ADD COLUMN IF NOT EXISTS polar_subscription_id VARCHAR(64) UNIQUE;
ALTER TABLE teams ADD COLUMN IF NOT EXISTS licence_expires_at TIMESTAMPTZ;
ALTER TABLE teams ADD COLUMN IF NOT EXISTS licence_note TEXT NOT NULL DEFAULT '';
ALTER TABLE teams ADD COLUMN IF NOT EXISTS granted_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_teams_licence ON teams (licence_source);

CREATE TABLE IF NOT EXISTS student_verifications (
    id             SERIAL PRIMARY KEY,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- Verified separately from the account email: students sign up with a
    -- personal address and only later prove they are at an institution.
    academic_email VARCHAR(255) NOT NULL,
    domain         VARCHAR(255) NOT NULL DEFAULT '',
    status         VARCHAR(16) NOT NULL DEFAULT 'pending',
    code_hash      TEXT NOT NULL DEFAULT '',
    attempts       INTEGER NOT NULL DEFAULT 0,
    evidence       TEXT NOT NULL DEFAULT '',
    reviewed_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    review_note    TEXT NOT NULL DEFAULT '',
    sent_at        TIMESTAMPTZ,
    verified_at    TIMESTAMPTZ,
    expires_at     TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_studentver_user   ON student_verifications (user_id);
CREATE INDEX IF NOT EXISTS ix_studentver_status ON student_verifications (status);

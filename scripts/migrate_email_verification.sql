-- Email verification columns. init_db() calls create_all(), which never adds
-- columns to a table that already exists, so run this once per database.

ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at    timestamptz;
ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_sent_at timestamptz;

-- Existing accounts shouldn't suddenly be nagged to confirm an address they've
-- been using for months. Drop this statement if you'd rather they all confirm.
UPDATE users SET email_verified_at = now() WHERE email_verified_at IS NULL;

ALTER TABLE api_keys
    ADD COLUMN IF NOT EXISTS admin_elevated_until TIMESTAMPTZ;

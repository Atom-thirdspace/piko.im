CREATE TABLE IF NOT EXISTS api_keys (
    id           SERIAL PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name         VARCHAR(80) NOT NULL DEFAULT '',
    prefix       VARCHAR(16) NOT NULL,
    key_hash     VARCHAR(64) NOT NULL UNIQUE,
    scopes       TEXT[] NOT NULL DEFAULT ARRAY['catalog:read']::TEXT[],
    requests     BIGINT NOT NULL DEFAULT 0,
    last_used_at TIMESTAMPTZ,
    last_ip      VARCHAR(64) NOT NULL DEFAULT '',
    expires_at   TIMESTAMPTZ,
    revoked_at   TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_api_keys_user   ON api_keys (user_id);
CREATE INDEX IF NOT EXISTS ix_api_keys_prefix ON api_keys (prefix);

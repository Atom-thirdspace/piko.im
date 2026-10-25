CREATE TABLE IF NOT EXISTS oauth_devices (
    id           SERIAL PRIMARY KEY,
    client_id    INTEGER NOT NULL REFERENCES oauth_clients(id) ON DELETE CASCADE,
    device_hash  VARCHAR(64) NOT NULL UNIQUE,
    user_code    VARCHAR(12) NOT NULL UNIQUE,
    scopes       TEXT[] NOT NULL DEFAULT '{}',
    user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
    approved_at  TIMESTAMPTZ,
    denied_at    TIMESTAMPTZ,
    consumed_at  TIMESTAMPTZ,
    last_poll_at TIMESTAMPTZ,
    expires_at   TIMESTAMPTZ NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_oauth_devices_client
    ON oauth_devices (client_id);

CREATE INDEX IF NOT EXISTS ix_oauth_devices_user_code
    ON oauth_devices (user_code);

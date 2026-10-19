CREATE TABLE IF NOT EXISTS oauth_clients (
    id             SERIAL PRIMARY KEY,
    client_id      VARCHAR(40)  NOT NULL UNIQUE,
    secret_hash    VARCHAR(64),
    name           VARCHAR(80)  NOT NULL,
    description    VARCHAR(300) NOT NULL DEFAULT '',
    homepage_url   VARCHAR(300) NOT NULL DEFAULT '',
    redirect_uris  TEXT[]       NOT NULL DEFAULT '{}',
    max_scopes     TEXT[]       NOT NULL DEFAULT '{}',
    owner_id       INTEGER REFERENCES users(id) ON DELETE CASCADE,
    first_party    BOOLEAN      NOT NULL DEFAULT FALSE,
    verified_at    TIMESTAMPTZ,
    revoked_at     TIMESTAMPTZ,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS oauth_codes (
    id              SERIAL PRIMARY KEY,
    code_hash       VARCHAR(64)  NOT NULL UNIQUE,
    client_id       INTEGER      NOT NULL REFERENCES oauth_clients(id) ON DELETE CASCADE,
    user_id         INTEGER      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    redirect_uri    VARCHAR(300) NOT NULL,
    scopes          TEXT[]       NOT NULL DEFAULT '{}',
    code_challenge  VARCHAR(128) NOT NULL,
    expires_at      TIMESTAMPTZ  NOT NULL,
    used_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS oauth_refresh_tokens (
    id          SERIAL PRIMARY KEY,
    token_hash  VARCHAR(64) NOT NULL UNIQUE,
    family      VARCHAR(32) NOT NULL,
    client_id   INTEGER NOT NULL REFERENCES oauth_clients(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    api_key_id  INTEGER REFERENCES api_keys(id) ON DELETE SET NULL,
    scopes      TEXT[] NOT NULL DEFAULT '{}',
    expires_at  TIMESTAMPTZ NOT NULL,
    used_at     TIMESTAMPTZ,
    revoked_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_oauth_refresh_family ON oauth_refresh_tokens (family);

ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS oauth_client_id INTEGER REFERENCES oauth_clients(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS ix_api_keys_oauth_client ON api_keys (oauth_client_id);

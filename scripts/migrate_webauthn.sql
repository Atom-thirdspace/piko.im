CREATE TABLE IF NOT EXISTS webauthn_credentials (
    id            serial PRIMARY KEY,
    user_id       integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    credential_id bytea NOT NULL,
    public_key    bytea NOT NULL,
    sign_count    bigint NOT NULL DEFAULT 0,
    transports    varchar(120) NOT NULL DEFAULT '',
    aaguid        varchar(64) NOT NULL DEFAULT '',
    name          varchar(80) NOT NULL DEFAULT 'Security key',
    -- A key enrolled while already an admin may unlock /admin. One enrolled
    -- as an ordinary second factor may not, so a stolen laptop with a
    -- user's key on it is not an admin credential.
    admin_capable boolean NOT NULL DEFAULT false,
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_used_at  timestamptz,
    CONSTRAINT uq_credential_id UNIQUE (credential_id)
);
CREATE INDEX IF NOT EXISTS ix_webauthn_user ON webauthn_credentials (user_id);

CREATE TABLE IF NOT EXISTS admin_login_codes (
    id         serial PRIMARY KEY,
    user_id    integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code_hash  varchar(255) NOT NULL,
    attempts   integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    used_at    timestamptz
);
CREATE INDEX IF NOT EXISTS ix_admin_code_live ON admin_login_codes (user_id, created_at DESC)
    WHERE used_at IS NULL;

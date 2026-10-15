CREATE TABLE IF NOT EXISTS redeem_codes (
    id SERIAL PRIMARY KEY,
    code VARCHAR(32) NOT NULL,
    reward VARCHAR(24) NOT NULL,
    amount      INTEGER NOT NULL DEFAULT 0,
    note        VARCHAR(200) NOT NULL DEFAULT '',
    max_uses    INTEGER NOT NULL DEFAULT 1,
    used_count  INTEGER NOT NULL DEFAULT 0,
    per_user    INTEGER NOT NULL DEFAULT 1,
    starts_at   TIMESTAMPTZ,
    expires_at  TIMESTAMPTZ,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_redeem_code UNIQUE (code),
    CONSTRAINT ck_redeem_amount CHECK (amount >= 0),
    CONSTRAINT ck_redeem_uses CHECK (max_uses >= 0 AND used_count >= 0)
);

CREATE INDEX IF NOT EXISTS ix_redeem_codes_active
    ON redeem_codes (is_active, expires_at);

CREATE TABLE IF NOT EXISTS redeem_uses (
    id         SERIAL PRIMARY KEY,
    code_id    INTEGER NOT NULL REFERENCES redeem_codes(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reward     VARCHAR(24) NOT NULL DEFAULT '',
    amount     INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_redeem_use UNIQUE (code_id, user_id)
);

CREATE INDEX IF NOT EXISTS ix_redeem_uses_user
    ON redeem_uses (user_id);
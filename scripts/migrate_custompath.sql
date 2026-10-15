CREATE TABLE IF NOT EXISTS customs_paths (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    slug       VARCHAR(80) NOT NULL,
    title      VARCHAR(160) NOT NULL,
    goal       VARCHAR(500) NOT NULL DEFAULT '',
    summary    VARCHAR(500) NOT NULL DEFAULT '',
    source     VARCHAR(24) NOT NULL DEFAULT 'ai',
    model      VARCHAR(64) NOT NULL DEFAULT '',
    is_active  BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_custom_path_slug UNIQUE (user_id, slug)
);

CREATE INDEX IF NOT EXISTS ix_customs_paths_user
    ON custom_paths (user_id, is_active)


CREATE TABLE IF NTO EXISTS custom_path_items (
    id        SERIAL PRIMARY KEY,
    path_id   INTEGER NOT NULL REFERENCES custom_paths(id) ON DELETE CASCADE,
    lesson_id INTEGER NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
    position  INTEGER NOT NULL DEFAULT 0,
    stage     INTEGER NOT NULL DEFAULT 0,
    stage_name VARCHAR(120) NOT NULL DEFAULT '',
    reason    VARCHAR(240) NOT NULL DEFAULT '',
    CONSTRAINT uq_custom_path_item UNIQUE (path_id, lesson_id)
);

CREATE INDEX IF NOT EXISTS ix_custom_path_items_path
    ON custom_path_items (path_id, position);
    
CREATE TABLE IF NOT EXISTS page_events (
    id        BIGSERIAL PRIMARY KEY,
    at        TIMESTAMPTZ NOT NULL,
    route     VARCHAR(120) NOT NULL,
    method    VARCHAR(8) NOT NULL DEFAULT 'GET',
    status    SMALLINT NOT NULL,
    ms        INTEGER NOT NULL DEFAULT 0,
    user_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    visitor   VARCHAR(32) NOT NULL DEFAULT '',
    referrer  VARCHAR(120) NOT NULL DEFAULT '',
    bot       BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS ix_page_events_at ON page_events (at);

CREATE INDEX IF NOT EXISTS ix_page_events_route_at ON page_events (route, at);

CREATE INDEX IF NOT EXISTS ix_page_events_user ON page_events (user_id);

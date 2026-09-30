CREATE TABLE IF NOT EXISTS subscriptions (
    id                     SERIAL PRIMARY KEY,
    user_id                INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    polar_subscription_id  VARCHAR(64) NOT NULL UNIQUE,
    polar_customer_id      VARCHAR(64) NOT NULL DEFAULT '',
    polar_product_id       VARCHAR(64) NOT NULL DEFAULT '',
    plan                   VARCHAR(32) NOT NULL DEFAULT '',
    status                 VARCHAR(32) NOT NULL DEFAULT 'incomplete',
    cancel_at_period_end   BOOLEAN NOT NULL DEFAULT false,
    current_period_start   TIMESTAMPTZ,
    current_period_end     TIMESTAMPTZ,
    started_at             TIMESTAMPTZ,
    ends_at                TIMESTAMPTZ,
    canceled_at            TIMESTAMPTZ,
    event_at               TIMESTAMPTZ,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_subscriptions_user   ON subscriptions (user_id);
CREATE INDEX IF NOT EXISTS ix_subscriptions_status ON subscriptions (status);

CREATE TABLE IF NOT EXISTS webhook_events (
    id           SERIAL PRIMARY KEY,
    source       VARCHAR(32) NOT NULL DEFAULT 'polar',
    event_id     VARCHAR(128) NOT NULL,
    event_type   VARCHAR(64) NOT NULL DEFAULT '',
    received_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, event_id)
);

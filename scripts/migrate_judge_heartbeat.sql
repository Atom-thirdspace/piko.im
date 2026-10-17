CREATE TABLE IF NOT EXISTS judge_heartbeat (
    id       SMALLINT PRIMARY KEY DEFAULT 1,
    beat_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    worker   VARCHAR(80) NOT NULL DEFAULT '',
    CONSTRAINT judge_heartbeat_single_row CHECK (id = 1)
);

INSERT INTO judge_heartbeat (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

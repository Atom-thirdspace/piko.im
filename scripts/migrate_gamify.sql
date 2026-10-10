ALTER TABLE users ADD COLUMN IF NOT EXISTS coin_balance  INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS solve_combo   INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS combo_best    INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS companion     VARCHAR(32) NOT NULL DEFAULT 'byte';
ALTER TABLE users ADD COLUMN IF NOT EXISTS equipped      JSONB NOT NULL DEFAULT '{}';
ALTER TABLE users ADD COLUMN IF NOT EXISTS wants_rival   BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS coin_events (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount     INTEGER NOT NULL,
    reason     VARCHAR(32) NOT NULL,
    ref        VARCHAR(64) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_coin_event UNIQUE (user_id, reason, ref)
);

CREATE INDEX IF NOT EXISTS ix_coin_events_user
    ON coin_events (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS user_cosmetics (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key         VARCHAR(48) NOT NULL,
    source      VARCHAR(16) NOT NULL DEFAULT 'bought',
    unlocked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_cosmetic UNIQUE (user_id, key)
);

CREATE TABLE IF NOT EXISTS topic_mastery (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    topic      VARCHAR(64) NOT NULL,
    points     DOUBLE PRECISION NOT NULL DEFAULT 0,
    peak       DOUBLE PRECISION NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_topic_mastery UNIQUE (user_id, topic)
);

CREATE TABLE IF NOT EXISTS speed_attempts (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    problem_id    INTEGER NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at   TIMESTAMPTZ,
    seconds       INTEGER,
    submission_id INTEGER REFERENCES submissions(id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_speed_attempt_open
    ON speed_attempts (user_id) WHERE finished_at IS NULL;

CREATE TABLE IF NOT EXISTS speed_records (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    problem_id    INTEGER NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
    seconds       INTEGER NOT NULL,
    submission_id INTEGER REFERENCES submissions(id) ON DELETE SET NULL,
    set_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_speed_record UNIQUE (user_id, problem_id)
);

CREATE TABLE IF NOT EXISTS seasons (
    id        SERIAL PRIMARY KEY,
    slug      VARCHAR(32) NOT NULL UNIQUE,
    name      VARCHAR(80) NOT NULL,
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at   TIMESTAMPTZ NOT NULL,
    closed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_seasons_window ON seasons (starts_at, ends_at);

CREATE TABLE IF NOT EXISTS season_results (
    id         SERIAL PRIMARY KEY,
    season_id  INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    score      INTEGER NOT NULL DEFAULT 0,
    rank       INTEGER NOT NULL DEFAULT 0,
    tier       VARCHAR(16) NOT NULL DEFAULT 'bronze',
    CONSTRAINT uq_season_result UNIQUE (season_id, user_id)
);

CREATE TABLE IF NOT EXISTS rivalries (
    id         SERIAL PRIMARY KEY,
    week       DATE NOT NULL,
    user_a_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- NULL means pacing against your own previous week rather than a person
    user_b_id  INTEGER REFERENCES users(id) ON DELETE CASCADE,
    ghost_score INTEGER NOT NULL DEFAULT 0,
    settled_at TIMESTAMPTZ,
    score_a    INTEGER NOT NULL DEFAULT 0,
    score_b    INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT uq_rival_a UNIQUE (week, user_a_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_rival_b
    ON rivalries (week, user_b_id) WHERE user_b_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS raids (
    id         SERIAL PRIMARY KEY,
    team_id    INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    boss_id    INTEGER NOT NULL REFERENCES bosses(id) ON DELETE CASCADE,
    hp_total   INTEGER NOT NULL,
    hp_left    INTEGER NOT NULL,
    status     VARCHAR(16) NOT NULL DEFAULT 'open',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ends_at    TIMESTAMPTZ NOT NULL,
    closed_at  TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_raid_open
    ON raids (team_id) WHERE status = 'open';

CREATE TABLE IF NOT EXISTS raid_contributions (
    id        SERIAL PRIMARY KEY,
    raid_id   INTEGER NOT NULL REFERENCES raids(id) ON DELETE CASCADE,
    user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    damage    INTEGER NOT NULL DEFAULT 0,
    fights    INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT uq_raid_contribution UNIQUE (raid_id, user_id)
);

ALTER TABLE boss_runs ADD COLUMN IF NOT EXISTS mode  VARCHAR(16) NOT NULL DEFAULT 'boss';
ALTER TABLE boss_runs ADD COLUMN IF NOT EXISTS stake VARCHAR(16) NOT NULL DEFAULT 'safe';
ALTER TABLE boss_runs ADD COLUMN IF NOT EXISTS lives INTEGER NOT NULL DEFAULT 0;
ALTER TABLE boss_runs ADD COLUMN IF NOT EXISTS score INTEGER NOT NULL DEFAULT 0;
ALTER TABLE boss_runs ADD COLUMN IF NOT EXISTS raid_id INTEGER
    REFERENCES raids(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_boss_runs_endless
    ON boss_runs (mode, score DESC) WHERE mode = 'endless';

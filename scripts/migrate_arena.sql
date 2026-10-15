CREATE TABLE IF NOT EXISTS boss_questions (
    id            SERIAL PRIMARY KEY,
    kind          VARCHAR(16)  NOT NULL DEFAULT 'choice',
    prompt        TEXT         NOT NULL,
    answer        VARCHAR(200) NOT NULL,
    alternates    TEXT[]       NOT NULL DEFAULT '{}',
    choices       JSONB        NOT NULL DEFAULT '[]',
    explain_md    TEXT         NOT NULL DEFAULT '',
    topic         VARCHAR(64),
    difficulty    VARCHAR(16)  NOT NULL DEFAULT 'easy',
    seconds       INTEGER      NOT NULL DEFAULT 20,
    status        VARCHAR(16)  NOT NULL DEFAULT 'draft',
    review_note   TEXT         NOT NULL DEFAULT '',
    submitted_at  TIMESTAMPTZ,
    published_at  TIMESTAMPTZ,
    created_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_boss_questions_pool
    ON boss_questions (status, difficulty, topic);

CREATE TABLE IF NOT EXISTS bosses (
    id         SERIAL PRIMARY KEY,
    slug       VARCHAR(64)  NOT NULL UNIQUE,
    name       VARCHAR(120) NOT NULL,
    blurb      TEXT         NOT NULL DEFAULT '',
    sigil      VARCHAR(16)  NOT NULL DEFAULT '',
    tier       INTEGER      NOT NULL DEFAULT 1,
    hp         INTEGER      NOT NULL DEFAULT 240,
    attack     INTEGER      NOT NULL DEFAULT 14,
    topic      VARCHAR(64),
    difficulty VARCHAR(16)  NOT NULL DEFAULT 'easy',
    position   INTEGER      NOT NULL DEFAULT 0,
    is_live    BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS boss_runs (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    boss_id       INTEGER NOT NULL REFERENCES bosses(id) ON DELETE CASCADE,
    seed          BIGINT  NOT NULL,
    plan          JSONB   NOT NULL DEFAULT '[]',
    cursor        INTEGER NOT NULL DEFAULT 0,
    boss_hp       INTEGER NOT NULL,
    player_hp     INTEGER NOT NULL,
    combo         INTEGER NOT NULL DEFAULT 0,
    best_combo    INTEGER NOT NULL DEFAULT 0,
    asked         INTEGER NOT NULL DEFAULT 0,
    correct       INTEGER NOT NULL DEFAULT 0,
    status        VARCHAR(16) NOT NULL DEFAULT 'active',
    xp_awarded    INTEGER NOT NULL DEFAULT 0,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_boss_runs_user
    ON boss_runs (user_id, started_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_boss_run_active
    ON boss_runs (user_id) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS boss_run_questions (
    id           SERIAL PRIMARY KEY,
    run_id       INTEGER NOT NULL REFERENCES boss_runs(id) ON DELETE CASCADE,
    question_id  INTEGER NOT NULL REFERENCES boss_questions(id) ON DELETE CASCADE,
    position     INTEGER NOT NULL,
    served_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deadline_at  TIMESTAMPTZ NOT NULL,
    answered_at  TIMESTAMPTZ,
    given        VARCHAR(200) NOT NULL DEFAULT '',
    correct      BOOLEAN NOT NULL DEFAULT FALSE,
    damage       INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT uq_brq_position UNIQUE (run_id, position),
    CONSTRAINT uq_brq_question UNIQUE (run_id, question_id)
);

CREATE INDEX IF NOT EXISTS ix_brq_open
    ON boss_run_questions (run_id) WHERE answered_at IS NULL;

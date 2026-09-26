CREATE TABLE IF NOT EXISTS problem_hints (
    id         serial PRIMARY KEY,
    problem_id integer NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
    position   integer NOT NULL DEFAULT 0,
    body_md    text NOT NULL DEFAULT '',
    cost_xp    integer NOT NULL DEFAULT 2,
    CONSTRAINT ck_hint_cost CHECK (cost_xp >= 0)
);
CREATE INDEX IF NOT EXISTS ix_hints_problem ON problem_hints (problem_id, position);

CREATE TABLE IF NOT EXISTS hint_reveals (
    id          serial PRIMARY KEY,
    user_id     integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    hint_id     integer NOT NULL REFERENCES problem_hints(id) ON DELETE CASCADE,
    revealed_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_hint_reveal UNIQUE (user_id, hint_id)
);
CREATE INDEX IF NOT EXISTS ix_reveals_user ON hint_reveals (user_id);

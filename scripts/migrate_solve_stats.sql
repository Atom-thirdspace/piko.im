CREATE TABLE IF NOT EXISTS problem_solves (
    id         serial PRIMARY KEY,
    user_id    integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    problem_id integer NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
    seconds    integer NOT NULL,
    attempts   integer NOT NULL,
    solved_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_problem_solve UNIQUE (user_id, problem_id),
    CONSTRAINT ck_solve_seconds CHECK (seconds >= 0)
);
CREATE INDEX IF NOT EXISTS ix_solves_speed ON problem_solves (problem_id, seconds);

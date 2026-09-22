CREATE TABLE IF NOT EXISTS tutor_messages (
    id         serial PRIMARY KEY,
    user_id    integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    lesson_id  integer REFERENCES lessons(id) ON DELETE SET NULL,
    problem_id integer REFERENCES problems(id) ON DELETE SET NULL,
    mode       varchar(16) NOT NULL DEFAULT 'hint',
    question   text NOT NULL,
    answer     text NOT NULL DEFAULT '',
    model      varchar(64) NOT NULL DEFAULT '',
    ok         boolean NOT NULL DEFAULT true,
    flagged    boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_tutor_user_time ON tutor_messages (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_tutor_flagged   ON tutor_messages (flagged) WHERE flagged;

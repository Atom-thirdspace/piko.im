ALTER TABLE classroom_members
    ADD COLUMN IF NOT EXISTS role VARCHAR(16) NOT NULL DEFAULT 'student';

CREATE TABLE IF NOT EXISTS classroom_posts (
    id           SERIAL PRIMARY KEY,
    classroom_id INTEGER NOT NULL REFERENCES classrooms(id) ON DELETE CASCADE,
    author_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    title        VARCHAR(200) NOT NULL,
    body_md      TEXT NOT NULL DEFAULT '',
    pinned       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_classroom_posts_room
    ON classroom_posts (classroom_id, created_at DESC);

CREATE TABLE IF NOT EXISTS saved_tests (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    problem_id INTEGER NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
    name       VARCHAR(80) NOT NULL DEFAULT '',
    stdin      TEXT NOT NULL DEFAULT '',
    expected   TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_saved_tests_user_problem
    ON saved_tests (user_id, problem_id);

ALTER TABLE scratch_runs
    ADD COLUMN IF NOT EXISTS saved_test_id INTEGER
    REFERENCES saved_tests(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS tutor_threads (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    lesson_id  INTEGER REFERENCES lessons(id) ON DELETE SET NULL,
    problem_id INTEGER REFERENCES problems(id) ON DELETE SET NULL,
    title      VARCHAR(200) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_tutor_threads_user_last
    ON tutor_threads (user_id, last_at DESC);

ALTER TABLE tutor_messages
    ADD COLUMN IF NOT EXISTS thread_id INTEGER
    REFERENCES tutor_threads(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_tutor_messages_thread
    ON tutor_messages (thread_id, created_at);

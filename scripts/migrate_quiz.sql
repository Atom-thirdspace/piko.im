CREATE TABLE IF NOT EXISTS lesson_questions (
    id          SERIAL PRIMARY KEY,
    lesson_id   INTEGER NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL DEFAULT 0,
    prompt      TEXT NOT NULL,
    explanation TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_lesson_questions_lesson_id
    ON lesson_questions (lesson_id);

CREATE TABLE IF NOT EXISTS lesson_choices (
    id          SERIAL PRIMARY KEY,
    question_id INTEGER NOT NULL REFERENCES lesson_questions(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL DEFAULT 0,
    text        VARCHAR(500) NOT NULL,
    is_correct  BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS ix_lesson_choices_question_id
    ON lesson_choices (question_id);

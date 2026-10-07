CREATE TABLE IF NOT EXISTS assignments (
    id            SERIAL PRIMARY KEY,
    classroom_id  INTEGER NOT NULL REFERENCES classrooms(id) ON DELETE CASCADE,
    title         VARCHAR(200) NOT NULL,
    note_md       TEXT NOT NULL DEFAULT '',
    due_at        TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_assignments_classroom_id ON assignments (classroom_id);

CREATE TABLE IF NOT EXISTS assignment_items (
    id            SERIAL PRIMARY KEY,
    assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
    position      INTEGER NOT NULL DEFAULT 0,
    problem_id    INTEGER REFERENCES problems(id) ON DELETE CASCADE,
    lesson_id     INTEGER REFERENCES lessons(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_assignment_items_assignment_id
    ON assignment_items (assignment_id);

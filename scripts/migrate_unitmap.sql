CREATE TABLE IF NOT EXISTS unit_prereqs (
    id               SERIAL PRIMARY KEY,
    unit_id          INTEGER NOT NULL REFERENCES units(id) ON DELETE CASCADE,
    requires_unit_id INTEGER NOT NULL REFERENCES units(id) ON DELETE CASCADE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_unit_prereq UNIQUE (unit_id, requires_unit_id),
    CONSTRAINT ck_unit_prereq_self CHECK (unit_id <> requires_unit_id)
);

CREATE INDEX IF NOT EXISTS ix_unit_prereqs_unit
    ON unit_prereqs (unit_id);

CREATE INDEX IF NOT EXISTS ix_unit_prereqs_requires
    ON unit_prereqs (requires_unit_id);

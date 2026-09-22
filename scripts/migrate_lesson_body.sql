-- Lesson concept text. create_all() never alters an existing table, so the
-- column has to be added by hand before the learning pages can read it.
ALTER TABLE lessons ADD COLUMN IF NOT EXISTS body_md text NOT NULL DEFAULT '';

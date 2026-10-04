-- Problems join the draft to review to published workflow that tracks,
-- units and lessons already use, and carry a reference solution the author
-- runs against their own tests before submitting.
-- Keep semicolons out of these comments - the runner splits on them first.

ALTER TABLE problems ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'draft';
ALTER TABLE problems ADD COLUMN IF NOT EXISTS review_note TEXT NOT NULL DEFAULT '';
ALTER TABLE problems ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMPTZ;
ALTER TABLE problems ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ;
ALTER TABLE problems ADD COLUMN IF NOT EXISTS created_by_id INTEGER
    REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE problems ADD COLUMN IF NOT EXISTS reference_source TEXT NOT NULL DEFAULT '';
ALTER TABLE problems ADD COLUMN IF NOT EXISTS reference_language VARCHAR(16) NOT NULL DEFAULT 'python';
ALTER TABLE problems ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS ix_problems_status ON problems (status);

-- Anything already in the catalogue was put there by an admin, so it stays
-- live rather than silently vanishing behind the new draft default.
UPDATE problems SET status = 'published', published_at = COALESCE(published_at, created_at)
WHERE status = 'draft' AND created_by_id IS NULL;

-- Authorship: an invited, DB-backed role that can draft content but not publish it.
-- Safe to run more than once.

ALTER TABLE users ADD COLUMN IF NOT EXISTS is_author BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE users ADD COLUMN IF NOT EXISTS author_since TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS author_invites (
    id            SERIAL PRIMARY KEY,
    -- sha256 of the link token. The raw token is shown to the admin once and
    -- never stored, so a dump of this table cannot be replayed as an invite.
    token_hash    VARCHAR(64) NOT NULL UNIQUE,
    email         VARCHAR(255),                      -- null = anyone with the link
    note          VARCHAR(200) NOT NULL DEFAULT '',
    invited_by_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    max_uses      INTEGER NOT NULL DEFAULT 1,
    uses          INTEGER NOT NULL DEFAULT 0,
    expires_at    TIMESTAMPTZ NOT NULL,
    revoked_at    TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_author_invites_inviter ON author_invites (invited_by_id);

CREATE TABLE IF NOT EXISTS author_invite_uses (
    id        SERIAL PRIMARY KEY,
    invite_id INTEGER NOT NULL REFERENCES author_invites(id) ON DELETE CASCADE,
    user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    used_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (invite_id, user_id)
);

-- Content workflow.
--
-- The column is created with DEFAULT 'published' so every row that already
-- exists is live, then the default flips to 'draft' for everything created
-- afterwards. Doing it this way rather than with a backfill UPDATE keeps the
-- script idempotent: on a second run the ADD COLUMN is skipped entirely, so
-- real drafts are never force-published.

ALTER TABLE tracks  ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'published';
ALTER TABLE units   ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'published';
ALTER TABLE lessons ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'published';

ALTER TABLE tracks  ALTER COLUMN status SET DEFAULT 'draft';
ALTER TABLE units   ALTER COLUMN status SET DEFAULT 'draft';
ALTER TABLE lessons ALTER COLUMN status SET DEFAULT 'draft';

ALTER TABLE tracks  ADD COLUMN IF NOT EXISTS created_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE units   ADD COLUMN IF NOT EXISTS created_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE lessons ADD COLUMN IF NOT EXISTS created_by_id INTEGER REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE tracks  ADD COLUMN IF NOT EXISTS review_note  TEXT NOT NULL DEFAULT '';
ALTER TABLE units   ADD COLUMN IF NOT EXISTS review_note  TEXT NOT NULL DEFAULT '';
ALTER TABLE lessons ADD COLUMN IF NOT EXISTS review_note  TEXT NOT NULL DEFAULT '';

ALTER TABLE tracks  ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMPTZ;
ALTER TABLE units   ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMPTZ;
ALTER TABLE lessons ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMPTZ;

ALTER TABLE tracks  ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ;
ALTER TABLE units   ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ;
ALTER TABLE lessons ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS ix_tracks_status  ON tracks  (status);
CREATE INDEX IF NOT EXISTS ix_units_status   ON units   (status);
CREATE INDEX IF NOT EXISTS ix_lessons_status ON lessons (status);

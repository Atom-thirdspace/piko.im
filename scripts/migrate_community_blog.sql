-- Discoverability is separate from the leaderboard flag on purpose: plenty of
-- people want to be findable for a team without being ranked, and vice versa.
ALTER TABLE users ADD COLUMN IF NOT EXISTS discoverable boolean NOT NULL DEFAULT true;
ALTER TABLE users ADD COLUMN IF NOT EXISTS bio text NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS follows (
    id          serial PRIMARY KEY,
    follower_id integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    followee_id integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_follow UNIQUE (follower_id, followee_id),
    CONSTRAINT ck_follow_not_self CHECK (follower_id <> followee_id)
);
CREATE INDEX IF NOT EXISTS ix_follows_followee ON follows (followee_id);

CREATE TABLE IF NOT EXISTS teams (
    id         serial PRIMARY KEY,
    slug       varchar(40) UNIQUE NOT NULL,
    name       varchar(60) NOT NULL,
    blurb      text NOT NULL DEFAULT '',
    visibility varchar(16) NOT NULL DEFAULT 'open',   -- open | code | closed
    join_code  varchar(16) NOT NULL DEFAULT '',
    owner_id   integer REFERENCES users(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS team_members (
    id        serial PRIMARY KEY,
    team_id   integer NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    user_id   integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role      varchar(16) NOT NULL DEFAULT 'member',  -- owner | member
    joined_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_team_member UNIQUE (team_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_team_members_user ON team_members (user_id);

CREATE TABLE IF NOT EXISTS posts (
    id           serial PRIMARY KEY,
    slug         varchar(80) UNIQUE NOT NULL,
    title        varchar(200) NOT NULL,
    summary      varchar(300) NOT NULL DEFAULT '',
    body_md      text NOT NULL DEFAULT '',
    cover_url    text,
    author_id    integer REFERENCES users(id) ON DELETE SET NULL,
    status       varchar(16) NOT NULL DEFAULT 'draft',   -- draft | published
    published_at timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_posts_live ON posts (published_at DESC)
    WHERE status = 'published';

-- The XP economy moves from per-row columns to a rule table in
-- server/xp_rules.py. The DB column keeps the name "xp" and NULL now
-- means "use the rule". Keep semicolons out of these comments: the runner
-- splits the file on them before it strips comment lines.

ALTER TABLE lessons  ALTER COLUMN xp DROP NOT NULL;
ALTER TABLE lessons  ALTER COLUMN xp DROP DEFAULT;
ALTER TABLE problems ALTER COLUMN xp DROP NOT NULL;
ALTER TABLE problems ALTER COLUMN xp DROP DEFAULT;

-- Every existing row adopts the new economy. Nothing in the current content
-- was priced deliberately enough to be worth keeping as an override, and
-- leaving the old values in place would quietly keep the old numbers alive.
UPDATE lessons  SET xp = NULL;
UPDATE problems SET xp = NULL;

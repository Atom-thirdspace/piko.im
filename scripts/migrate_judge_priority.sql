ALTER TABLE judge_jobs ADD COLUMN IF NOT EXISTS priority INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS ix_judge_jobs_claim
    ON judge_jobs (status, priority DESC, created_at);

ALTER TABLE external_gpu_jobs
    ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now();

ALTER TABLE external_gpu_jobs
    DROP CONSTRAINT IF EXISTS external_gpu_jobs_status_check;

ALTER TABLE external_gpu_jobs
    ADD CONSTRAINT external_gpu_jobs_status_check
    CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed', 'dead_letter', 'cancelled')
    );

CREATE INDEX IF NOT EXISTS idx_external_gpu_jobs_scheduled_claim
    ON external_gpu_jobs (platform, status, next_attempt_at, created_at)
    WHERE status = 'queued';

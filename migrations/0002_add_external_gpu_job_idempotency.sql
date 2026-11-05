ALTER TABLE external_gpu_jobs
    ADD COLUMN IF NOT EXISTS idempotency_key TEXT,
    ADD COLUMN IF NOT EXISTS request_hash CHAR(64);

CREATE UNIQUE INDEX IF NOT EXISTS uq_external_gpu_jobs_idempotency_key
    ON external_gpu_jobs (idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS external_gpu_jobs (
    job_id TEXT PRIMARY KEY,
    platform TEXT NOT NULL CHECK (platform IN ('kaggle', 'colab')),
    task TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed', 'dead_letter')
    ),
    input_asset TEXT NOT NULL,
    prompt TEXT,
    model_id TEXT NOT NULL,
    model_revision TEXT NOT NULL,
    options JSONB NOT NULL DEFAULT '{}'::jsonb,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    worker_id TEXT,
    lease_expires_at TIMESTAMPTZ,
    output_asset TEXT,
    result_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (
        (status = 'running' AND worker_id IS NOT NULL AND lease_expires_at IS NOT NULL)
        OR
        (status <> 'running' AND worker_id IS NULL AND lease_expires_at IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_external_gpu_jobs_claim
    ON external_gpu_jobs (platform, status, created_at);

CREATE INDEX IF NOT EXISTS idx_external_gpu_jobs_expired_leases
    ON external_gpu_jobs (lease_expires_at)
    WHERE status = 'running';

CREATE INDEX IF NOT EXISTS idx_external_gpu_jobs_updated_at
    ON external_gpu_jobs (updated_at DESC);

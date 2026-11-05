ALTER TABLE external_gpu_jobs
    ADD COLUMN IF NOT EXISTS min_gpu_vram_gb DOUBLE PRECISION NOT NULL DEFAULT 0
        CHECK (min_gpu_vram_gb >= 0),
    ADD COLUMN IF NOT EXISTS min_memory_gb DOUBLE PRECISION NOT NULL DEFAULT 0
        CHECK (min_memory_gb >= 0);

CREATE TABLE IF NOT EXISTS external_gpu_workers (
    worker_id TEXT PRIMARY KEY,
    platform TEXT NOT NULL CHECK (platform IN ('kaggle', 'colab')),
    token_hash CHAR(64) NOT NULL UNIQUE,
    token_expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'provisioned'
        CHECK (status IN ('provisioned', 'active', 'revoked')),
    runtime_version TEXT,
    gpu_model TEXT,
    gpu_vram_gb DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (gpu_vram_gb >= 0),
    available_gpu_memory_gb DOUBLE PRECISION NOT NULL DEFAULT 0
        CHECK (available_gpu_memory_gb >= 0),
    cuda_version TEXT,
    frameworks JSONB NOT NULL DEFAULT '[]'::jsonb,
    supported_tasks JSONB NOT NULL DEFAULT '[]'::jsonb,
    available_memory_gb DOUBLE PRECISION NOT NULL DEFAULT 0
        CHECK (available_memory_gb >= 0),
    capacity INTEGER NOT NULL DEFAULT 1 CHECK (capacity BETWEEN 1 AND 32),
    last_heartbeat_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_external_gpu_workers_active
    ON external_gpu_workers (platform, status, token_expires_at);

CREATE INDEX IF NOT EXISTS idx_external_gpu_workers_heartbeat
    ON external_gpu_workers (last_heartbeat_at DESC)
    WHERE status = 'active';

CREATE TABLE IF NOT EXISTS model_registry_versions (
    model_id TEXT NOT NULL,
    revision CHAR(40) NOT NULL CHECK (revision ~ '^[0-9a-fA-F]{40}$'),
    model_name TEXT NOT NULL,
    family TEXT NOT NULL,
    source TEXT NOT NULL,
    license_id TEXT NOT NULL,
    intended_use TEXT NOT NULL,
    input_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
    hardware_requirements JSONB NOT NULL DEFAULT '{}'::jsonb,
    runtime_dependencies JSONB NOT NULL DEFAULT '{}'::jsonb,
    license_review_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (license_review_status IN ('pending', 'approved', 'rejected')),
    validation_status TEXT NOT NULL DEFAULT 'not_run'
        CHECK (validation_status IN ('not_run', 'passed', 'failed')),
    evaluation_results JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'pending_review'
        CHECK (status IN ('pending_review', 'approved', 'disabled', 'rejected')),
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (model_id, revision)
);

CREATE INDEX IF NOT EXISTS idx_model_registry_approved_family
    ON model_registry_versions (family, model_id)
    WHERE status = 'approved';

CREATE INDEX IF NOT EXISTS idx_model_registry_status_updated
    ON model_registry_versions (status, updated_at DESC);

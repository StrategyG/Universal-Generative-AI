-- Scope general generation history to the authenticated caller's tenant and project.
-- Existing rows remain unowned (NULL) and are intentionally inaccessible to OIDC users.
ALTER TABLE generation_jobs
    ADD COLUMN IF NOT EXISTS tenant_id TEXT,
    ADD COLUMN IF NOT EXISTS owner_subject TEXT,
    ADD COLUMN IF NOT EXISTS project_id TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'generation_jobs_owner_scope_complete'
    ) THEN
        ALTER TABLE generation_jobs
            ADD CONSTRAINT generation_jobs_owner_scope_complete
            CHECK (
                (tenant_id IS NULL AND owner_subject IS NULL)
                OR (tenant_id IS NOT NULL AND owner_subject IS NOT NULL)
            ) NOT VALID;
    END IF;
END;
$;

CREATE INDEX IF NOT EXISTS idx_generation_jobs_tenant_owner_updated
    ON generation_jobs (tenant_id, owner_subject, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_generation_jobs_tenant_project_updated
    ON generation_jobs (tenant_id, project_id, updated_at DESC);

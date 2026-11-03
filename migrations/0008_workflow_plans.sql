CREATE TABLE IF NOT EXISTS workflow_plans (
    plan_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    owner_subject TEXT NOT NULL,
    project_id TEXT NOT NULL,
    domain TEXT NOT NULL CHECK (domain IN ('coding', 'film', 'workflow')),
    policy_version TEXT NOT NULL,
    plan_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_workflow_plans_tenant_project_created
    ON workflow_plans (tenant_id, project_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_workflow_plans_tenant_owner_created
    ON workflow_plans (tenant_id, owner_subject, created_at DESC);

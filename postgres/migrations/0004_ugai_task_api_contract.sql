-- Versioned durable task API contract and encrypted notebook input storage.
-- Apply with the UGAI workflow runtime role configured as a non-owner, NOBYPASSRLS login.
ALTER TABLE ugai_workflow.tasks
    ADD COLUMN IF NOT EXISTS project_id text,
    ADD COLUMN IF NOT EXISTS correlation_id uuid;

CREATE TABLE IF NOT EXISTS ugai_workflow.task_payloads (
    task_id uuid PRIMARY KEY REFERENCES ugai_workflow.tasks(task_id),
    tenant_id text NOT NULL,
    key_id text NOT NULL,
    ciphertext bytea NOT NULL,
    payload_sha256 text NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_ugai_task_payload_ciphertext_size
        CHECK (octet_length(ciphertext) BETWEEN 1 AND 262144),
    CONSTRAINT ck_ugai_task_payload_key_id
        CHECK (length(trim(key_id)) BETWEEN 1 AND 64)
);

CREATE INDEX IF NOT EXISTS ugai_workflow_task_payloads_tenant_idx
    ON ugai_workflow.task_payloads (tenant_id, created_at DESC);

ALTER TABLE ugai_workflow.task_payloads ENABLE ROW LEVEL SECURITY;
ALTER TABLE ugai_workflow.task_payloads FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS ugai_workflow_task_payloads_runtime
    ON ugai_workflow.task_payloads;
CREATE POLICY ugai_workflow_task_payloads_runtime
    ON ugai_workflow.task_payloads
    FOR ALL TO ugai_workflow_runtime
    USING (
        tenant_id = nullif(current_setting('app.ugai_tenant_id', true), '')
        AND EXISTS (
            SELECT 1
            FROM ugai_workflow.tasks task
            WHERE task.task_id = task_payloads.task_id
              AND task.tenant_id = task_payloads.tenant_id
        )
    )
    WITH CHECK (
        tenant_id = nullif(current_setting('app.ugai_tenant_id', true), '')
        AND EXISTS (
            SELECT 1
            FROM ugai_workflow.tasks task
            WHERE task.task_id = task_payloads.task_id
              AND task.tenant_id = task_payloads.tenant_id
        )
    );

REVOKE ALL ON TABLE ugai_workflow.task_payloads FROM PUBLIC;
GRANT SELECT, INSERT ON ugai_workflow.task_payloads TO ugai_workflow_runtime;

COMMENT ON TABLE ugai_workflow.task_payloads IS
    'Encrypted task input payloads only. Keys remain in an external secret manager; plaintext is never stored here.';

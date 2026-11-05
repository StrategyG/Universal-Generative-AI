-- Durable Notebook task results and independently authenticated worker heartbeats.
-- Apply after 0005_ugai_workflow_outcome_unknown.sql using a reviewed forward-only release.
-- Create a separate NOLOGIN role. Provision a worker login through secret management,
-- then GRANT ugai_workflow_worker TO <worker_login>; never reuse the API login.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ugai_workflow_worker') THEN
        CREATE ROLE ugai_workflow_worker NOLOGIN NOBYPASSRLS;
    END IF;
END
$$;

ALTER TABLE ugai_workflow.tasks
    ADD CONSTRAINT uq_ugai_workflow_task_identity
    UNIQUE (task_id, tenant_id, actor_id, project_id);

CREATE TABLE ugai_workflow.task_results (
    tenant_id text NOT NULL,
    task_id uuid NOT NULL,
    actor_id text NOT NULL,
    project_id text NOT NULL,
    key_id text NOT NULL CHECK (length(trim(key_id)) BETWEEN 1 AND 64),
    ciphertext bytea NOT NULL CHECK (octet_length(ciphertext) BETWEEN 1 AND 262144),
    payload_sha256 text NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT pk_ugai_workflow_task_results PRIMARY KEY (tenant_id, task_id),
    CONSTRAINT fk_ugai_workflow_task_results_identity
        FOREIGN KEY (task_id, tenant_id, actor_id, project_id)
        REFERENCES ugai_workflow.tasks (task_id, tenant_id, actor_id, project_id)
        ON DELETE RESTRICT
);

CREATE INDEX ugai_workflow_task_results_project_idx
    ON ugai_workflow.task_results (tenant_id, project_id, created_at DESC);

ALTER TABLE ugai_workflow.task_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE ugai_workflow.task_results FORCE ROW LEVEL SECURITY;

CREATE POLICY ugai_workflow_task_results_api_read
    ON ugai_workflow.task_results
    FOR SELECT TO ugai_workflow_runtime
    USING (
        tenant_id = nullif(current_setting('app.ugai_tenant_id', true), '')
        AND EXISTS (
            SELECT 1
            FROM ugai_workflow.tasks task
            WHERE task.task_id = task_results.task_id
              AND task.tenant_id = task_results.tenant_id
              AND task.actor_id = task_results.actor_id
              AND task.project_id = task_results.project_id
        )
    );

CREATE POLICY ugai_workflow_task_results_worker_read
    ON ugai_workflow.task_results
    FOR SELECT TO ugai_workflow_worker
    USING (
        tenant_id = nullif(current_setting('app.ugai_tenant_id', true), '')
    );

CREATE POLICY ugai_workflow_task_results_worker_insert
    ON ugai_workflow.task_results
    FOR INSERT TO ugai_workflow_worker
    WITH CHECK (
        tenant_id = nullif(current_setting('app.ugai_tenant_id', true), '')
        AND EXISTS (
            SELECT 1
            FROM ugai_workflow.tasks task
            WHERE task.task_id = task_results.task_id
              AND task.tenant_id = task_results.tenant_id
              AND task.actor_id = task_results.actor_id
              AND task.project_id = task_results.project_id
        )
    );

REVOKE ALL ON TABLE ugai_workflow.task_results FROM PUBLIC, anon, authenticated;
GRANT SELECT ON TABLE ugai_workflow.task_results TO ugai_workflow_runtime;
GRANT SELECT, INSERT ON TABLE ugai_workflow.task_results TO ugai_workflow_worker;

CREATE OR REPLACE FUNCTION ugai_workflow.reject_task_result_mutation()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    RAISE EXCEPTION 'UGAI task results are immutable';
END;
$$;
REVOKE ALL ON FUNCTION ugai_workflow.reject_task_result_mutation() FROM PUBLIC;
CREATE TRIGGER ugai_workflow_task_results_immutable
    BEFORE UPDATE OR DELETE ON ugai_workflow.task_results
    FOR EACH ROW EXECUTE FUNCTION ugai_workflow.reject_task_result_mutation();
CREATE TRIGGER ugai_workflow_task_results_no_truncate
    BEFORE TRUNCATE ON ugai_workflow.task_results
    FOR EACH STATEMENT EXECUTE FUNCTION ugai_workflow.reject_task_result_mutation();

CREATE TABLE ugai_workflow.workers (
    tenant_id text NOT NULL,
    worker_id text NOT NULL,
    task_types text[] NOT NULL CHECK (cardinality(task_types) BETWEEN 1 AND 32),
    active boolean NOT NULL DEFAULT true,
    last_heartbeat_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT pk_ugai_workflow_workers PRIMARY KEY (tenant_id, worker_id),
    CONSTRAINT ck_ugai_workflow_worker_task_types_valid
        CHECK (
            cardinality(task_types) BETWEEN 1 AND 32
            AND array_position(task_types, NULL) IS NULL
        )
);

CREATE INDEX ugai_workflow_workers_health_idx
    ON ugai_workflow.workers (tenant_id, last_heartbeat_at DESC)
    WHERE active = true;

ALTER TABLE ugai_workflow.workers ENABLE ROW LEVEL SECURITY;
ALTER TABLE ugai_workflow.workers FORCE ROW LEVEL SECURITY;

CREATE POLICY ugai_workflow_workers_api_read
    ON ugai_workflow.workers
    FOR SELECT TO ugai_workflow_runtime
    USING (tenant_id = nullif(current_setting('app.ugai_tenant_id', true), ''));

CREATE POLICY ugai_workflow_workers_worker_write
    ON ugai_workflow.workers
    FOR ALL TO ugai_workflow_worker
    USING (tenant_id = nullif(current_setting('app.ugai_tenant_id', true), ''))
    WITH CHECK (tenant_id = nullif(current_setting('app.ugai_tenant_id', true), ''));

REVOKE ALL ON TABLE ugai_workflow.workers FROM PUBLIC, anon, authenticated;
GRANT SELECT ON TABLE ugai_workflow.workers TO ugai_workflow_runtime;
GRANT SELECT, INSERT, UPDATE ON TABLE ugai_workflow.workers TO ugai_workflow_worker;

-- Worker execution rights are deliberately distinct from API intake rights.
GRANT USAGE ON SCHEMA ugai_workflow TO ugai_workflow_worker;
GRANT SELECT, UPDATE (
    state, version, retry_count, retryable, available_at,
    lease_owner, lease_token, lease_expires_at, approval_reference,
    decision_digest, plan_digest, error_code, updated_at
) ON ugai_workflow.tasks TO ugai_workflow_worker;
GRANT SELECT, INSERT ON ugai_workflow.events TO ugai_workflow_worker;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA ugai_workflow TO ugai_workflow_worker;
GRANT SELECT ON ugai_workflow.task_payloads TO ugai_workflow_worker;

CREATE POLICY ugai_workflow_tasks_worker
    ON ugai_workflow.tasks
    FOR ALL TO ugai_workflow_worker
    USING (tenant_id = nullif(current_setting('app.ugai_tenant_id', true), ''))
    WITH CHECK (tenant_id = nullif(current_setting('app.ugai_tenant_id', true), ''));

CREATE POLICY ugai_workflow_events_worker_read
    ON ugai_workflow.events
    FOR SELECT TO ugai_workflow_worker
    USING (
        EXISTS (
            SELECT 1 FROM ugai_workflow.tasks task
            WHERE task.task_id = events.task_id
              AND task.tenant_id = nullif(current_setting('app.ugai_tenant_id', true), '')
        )
    );

CREATE POLICY ugai_workflow_events_worker_insert
    ON ugai_workflow.events
    FOR INSERT TO ugai_workflow_worker
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM ugai_workflow.tasks task
            WHERE task.task_id = events.task_id
              AND task.tenant_id = nullif(current_setting('app.ugai_tenant_id', true), '')
        )
    );

CREATE POLICY ugai_workflow_task_payloads_worker_read
    ON ugai_workflow.task_payloads
    FOR SELECT TO ugai_workflow_worker
    USING (
        tenant_id = nullif(current_setting('app.ugai_tenant_id', true), '')
        AND EXISTS (
            SELECT 1 FROM ugai_workflow.tasks task
            WHERE task.task_id = task_payloads.task_id
              AND task.tenant_id = task_payloads.tenant_id
        )
    );

COMMENT ON TABLE ugai_workflow.task_results IS
    'Immutable encrypted Notebook reasoning results, scoped to task tenant, actor and project.';
COMMENT ON TABLE ugai_workflow.workers IS
    'Tenant-scoped worker heartbeat registry. API credentials are read-only; only worker-role credentials may write heartbeats.';
COMMENT ON ROLE ugai_workflow_worker IS
    'Dedicated non-login least-privilege group for supervised workflow workers; provision individual login membership externally.';

BEGIN;
CREATE SCHEMA IF NOT EXISTS ugai_audit;

CREATE TABLE IF NOT EXISTS ugai_audit.decision_events (
    event_id text PRIMARY KEY,
    workflow_id text NOT NULL,
    decision_id text NOT NULL,
    actor_id text NOT NULL,
    stage text NOT NULL CHECK (length(stage) BETWEEN 1 AND 128),
    outcome text NOT NULL CHECK (length(outcome) BETWEEN 1 AND 128),
    occurred_at timestamptz NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(details) = 'object'),
    inserted_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS decision_events_workflow_time_idx
    ON ugai_audit.decision_events (workflow_id, occurred_at);
CREATE INDEX IF NOT EXISTS decision_events_decision_time_idx
    ON ugai_audit.decision_events (decision_id, occurred_at);
CREATE INDEX IF NOT EXISTS decision_events_actor_time_idx
    ON ugai_audit.decision_events (actor_id, occurred_at);

CREATE TABLE IF NOT EXISTS ugai_audit.evidence_objects (
    evidence_id text PRIMARY KEY,
    actor_id text NOT NULL,
    drive_file_id text NOT NULL UNIQUE,
    file_name text NOT NULL,
    mime_type text NOT NULL,
    sha256 char(64) NOT NULL CHECK (sha256 ~ '^[a-f0-9]{64}$'),
    size_bytes bigint NOT NULL CHECK (size_bytes > 0),
    web_view_link text,
    source_uri text,
    registered_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION ugai_audit.reject_audit_mutation()
RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, ugai_audit
AS $$
BEGIN
    RAISE EXCEPTION 'UGAI audit records are append-only';
END;
$$;
DROP TRIGGER IF EXISTS decision_events_no_update_delete ON ugai_audit.decision_events;
CREATE TRIGGER decision_events_no_update_delete
    BEFORE UPDATE OR DELETE ON ugai_audit.decision_events
    FOR EACH ROW EXECUTE FUNCTION ugai_audit.reject_audit_mutation();

REVOKE ALL ON SCHEMA ugai_audit FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA ugai_audit FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA ugai_audit FROM PUBLIC;

-- Provision ugai_runtime separately through the DBA process.
-- GRANT USAGE ON SCHEMA ugai_audit TO ugai_runtime;
-- GRANT INSERT, SELECT ON ugai_audit.decision_events TO ugai_runtime;
-- GRANT INSERT, SELECT ON ugai_audit.evidence_objects TO ugai_runtime;
-- Never grant UPDATE, DELETE, TRUNCATE, ownership, or superuser to the runtime role.
COMMIT;

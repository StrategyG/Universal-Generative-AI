-- Generic PostgreSQL decision-audit storage; no Supabase/PostgREST dependency.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ugai_audit_writer') THEN
        CREATE ROLE ugai_audit_writer NOLOGIN;
    END IF;
END
$$;

CREATE SCHEMA IF NOT EXISTS ugai_audit;
REVOKE ALL ON SCHEMA ugai_audit FROM PUBLIC;
GRANT USAGE ON SCHEMA ugai_audit TO ugai_audit_writer;

CREATE TABLE IF NOT EXISTS ugai_audit.decision_events (
    event_id text PRIMARY KEY,
    workflow_id text NOT NULL,
    decision_id text NOT NULL,
    actor_id text NOT NULL,
    stage text NOT NULL,
    outcome text NOT NULL,
    occurred_at timestamptz NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    inserted_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT decision_events_event_id_nonempty CHECK (length(trim(event_id)) > 0),
    CONSTRAINT decision_events_workflow_id_nonempty CHECK (length(trim(workflow_id)) > 0),
    CONSTRAINT decision_events_decision_id_nonempty CHECK (length(trim(decision_id)) > 0),
    CONSTRAINT decision_events_actor_id_nonempty CHECK (length(trim(actor_id)) > 0),
    CONSTRAINT decision_events_stage_nonempty CHECK (length(trim(stage)) > 0),
    CONSTRAINT decision_events_outcome_nonempty CHECK (length(trim(outcome)) > 0),
    CONSTRAINT decision_events_field_lengths CHECK (
        length(event_id) <= 128
        AND length(workflow_id) <= 128
        AND length(decision_id) <= 128
        AND length(actor_id) <= 255
        AND length(stage) <= 100
        AND length(outcome) <= 100
    ),
    CONSTRAINT decision_events_details_object CHECK (jsonb_typeof(details) = 'object')
);

CREATE INDEX IF NOT EXISTS decision_events_decision_id_idx
    ON ugai_audit.decision_events (decision_id, occurred_at);
CREATE INDEX IF NOT EXISTS decision_events_workflow_id_idx
    ON ugai_audit.decision_events (workflow_id, occurred_at);

REVOKE ALL ON TABLE ugai_audit.decision_events FROM PUBLIC;
GRANT INSERT ON TABLE ugai_audit.decision_events TO ugai_audit_writer;

CREATE OR REPLACE FUNCTION ugai_audit.reject_decision_event_mutation()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    RAISE EXCEPTION 'UGAI decision audit events are append-only';
END;
$$;

REVOKE ALL ON FUNCTION ugai_audit.reject_decision_event_mutation() FROM PUBLIC;
DROP TRIGGER IF EXISTS decision_events_no_update_delete ON ugai_audit.decision_events;
CREATE TRIGGER decision_events_no_update_delete
    BEFORE UPDATE OR DELETE ON ugai_audit.decision_events
    FOR EACH ROW EXECUTE FUNCTION ugai_audit.reject_decision_event_mutation();
DROP TRIGGER IF EXISTS decision_events_no_truncate ON ugai_audit.decision_events;
CREATE TRIGGER decision_events_no_truncate
    BEFORE TRUNCATE ON ugai_audit.decision_events
    FOR EACH STATEMENT EXECUTE FUNCTION ugai_audit.reject_decision_event_mutation();

COMMENT ON SCHEMA ugai_audit IS
    'Private PostgreSQL schema for append-only UGAI decision workflow audit records.';

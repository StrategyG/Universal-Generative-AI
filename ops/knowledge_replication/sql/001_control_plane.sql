-- UGAI hybrid replication control plane.
-- Apply to the PostgreSQL VM target only. This file does not modify Supabase.
BEGIN;

CREATE SCHEMA IF NOT EXISTS ugai_sync;

CREATE TABLE IF NOT EXISTS ugai_sync.stream_checkpoints (
    stream_name text PRIMARY KEY,
    last_event_id uuid,
    last_source_position text,
    last_event_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    lease_owner text,
    lease_expires_at timestamptz,
    fencing_token bigint NOT NULL DEFAULT 0,
    CHECK (stream_name <> '')
);

CREATE TABLE IF NOT EXISTS ugai_sync.event_receipts (
    event_id uuid PRIMARY KEY,
    stream_name text NOT NULL,
    aggregate_key text NOT NULL,
    event_type text NOT NULL,
    schema_version integer NOT NULL CHECK (schema_version > 0),
    source_position text,
    payload_sha256 char(64) NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (stream_name, aggregate_key, event_id)
);

CREATE INDEX IF NOT EXISTS event_receipts_stream_applied_idx
    ON ugai_sync.event_receipts (stream_name, applied_at DESC);

CREATE TABLE IF NOT EXISTS ugai_sync.sync_runs (
    run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    stream_name text NOT NULL,
    mode text NOT NULL CHECK (mode IN ('baseline', 'incremental', 'reconcile', 'restore_test')),
    status text NOT NULL CHECK (status IN ('planned', 'running', 'succeeded', 'failed', 'quarantined')),
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    source_watermark text,
    destination_watermark text,
    rows_seen bigint NOT NULL DEFAULT 0 CHECK (rows_seen >= 0),
    rows_applied bigint NOT NULL DEFAULT 0 CHECK (rows_applied >= 0),
    rows_skipped bigint NOT NULL DEFAULT 0 CHECK (rows_skipped >= 0),
    error_code text,
    error_summary text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    CHECK ((status = 'running' AND finished_at IS NULL) OR status <> 'running')
);

CREATE INDEX IF NOT EXISTS sync_runs_stream_started_idx
    ON ugai_sync.sync_runs (stream_name, started_at DESC);

CREATE TABLE IF NOT EXISTS ugai_sync.quarantine (
    quarantine_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id uuid,
    stream_name text NOT NULL,
    reason_code text NOT NULL,
    safe_summary text NOT NULL,
    payload_sha256 char(64),
    quarantined_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    resolution text
);

CREATE INDEX IF NOT EXISTS quarantine_unresolved_idx
    ON ugai_sync.quarantine (quarantined_at)
    WHERE resolved_at IS NULL;

CREATE TABLE IF NOT EXISTS ugai_sync.backup_manifests (
    backup_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_identifier text NOT NULL,
    captured_at timestamptz NOT NULL,
    artifact_name text NOT NULL,
    artifact_format text NOT NULL CHECK (artifact_format IN ('pg_dump_custom', 'directory', 'plain_sql')),
    ciphertext_sha256 char(64) NOT NULL,
    ciphertext_bytes bigint NOT NULL CHECK (ciphertext_bytes > 0),
    encryption_scheme text NOT NULL,
    key_reference text NOT NULL,
    object_inventory jsonb NOT NULL DEFAULT '{}'::jsonb,
    restore_tested_at timestamptz,
    restore_test_status text CHECK (restore_test_status IN ('passed', 'failed', 'not_run')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (artifact_name, ciphertext_sha256)
);

CREATE TABLE IF NOT EXISTS ugai_sync.audit_log (
    audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    actor text NOT NULL,
    action text NOT NULL,
    object_type text NOT NULL,
    object_key text,
    outcome text NOT NULL CHECK (outcome IN ('allowed', 'denied', 'success', 'failure')),
    correlation_id uuid,
    details jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS audit_log_occurred_idx
    ON ugai_sync.audit_log (occurred_at DESC);

COMMENT ON SCHEMA ugai_sync IS
    'UGAI hybrid synchronization control plane; contains metadata, receipts and checkpoints, not RAG source content.';

COMMIT;

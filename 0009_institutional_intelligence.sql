CREATE TABLE IF NOT EXISTS institutional_audit_ledger (
    seq BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    tenant_id TEXT NOT NULL,
    actor_identity TEXT NOT NULL,
    operation TEXT NOT NULL,
    risk_classification TEXT NOT NULL CHECK (risk_classification IN ('R0', 'R1', 'R2', 'R3', 'R4')),
    idempotency_key TEXT NOT NULL,
    details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    previous_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS institutional_evidence_claims (
    claim_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    claim_description TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_version TEXT NOT NULL,
    publication_date TEXT NOT NULL,
    relevant_excerpt TEXT NOT NULL,
    verification_method TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    grade TEXT NOT NULL CHECK (grade IN ('A', 'B', 'C', 'D')),
    verification_status TEXT NOT NULL,
    CHECK (NOT (grade = 'D' AND verification_status = 'VERIFIED'))
);

CREATE TABLE IF NOT EXISTS institutional_artifacts (
    artifact_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    sha256 CHAR(64) NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes BIGINT NOT NULL CHECK (size_bytes > 0),
    domain TEXT NOT NULL CHECK (domain IN ('coding', 'film', 'workflow')),
    model_id TEXT NOT NULL,
    model_revision TEXT NOT NULL,
    verified_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

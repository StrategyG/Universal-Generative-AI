# UGAI Application Data Model and Migration Boundary

**Status:** proposed logical model; no database objects are created by this document.

## 1. Ownership principle

Institutional RAG remains the authority for source documents, evidence excerpts, source hashes, embedding attestations, review quorum, publication state, and knowledge relations. UGAI owns application execution state. Do not duplicate evidence approval fields inside UGAI and do not add UGAI workflow columns to existing RAG tables.

Proposed application schema: ugai. It is separate from institutional_rag and rag.

## 2. Logical entities

| Entity | Key | Purpose | Retention |
|---|---|---|---|
| conversations | conversation_id | User-facing thread metadata and ownership | Tenant policy |
| messages | message_id | User and assistant visible messages | Tenant policy |
| workflow_runs | workflow_id | State, request association, budgets and terminal outcome | Operational/audit policy |
| workflow_steps | step_id | Validated step plan, dependencies and status | Workflow retention |
| step_attempts | attempt_id | Attempt timing, retry and error category | Operational policy |
| tool_invocations | tool_invocation_id | Tool/version, validated args hash, approval and side-effect outcome | Audit policy |
| provider_usage | usage_id | Provider/model, token usage, latency, cost estimate | Billing/analytics policy |
| artifacts | artifact_id | File/object metadata, hash, storage key and access policy | Artifact retention |
| idempotency_records | idempotency_id | Request-key hash and associated workflow/result | TTL + reconciliation |
| audit_events | event_id | Append-only security and workflow events | Security retention |

## 3. Relationship model

- One conversation has many messages and workflow runs.
- One workflow has many workflow steps.
- One step has many attempt records.
- One workflow may have many tool invocations, provider usage records, and artifacts.
- An artifact may be linked to the workflow that created it and the principal that owns it.
- Workflow evidence references are stored as source/evidence IDs and source hashes, not as a second mutable copy of the RAG approval record.
- An audit event references principal, workflow, action type, timestamp, and a redacted detail payload.

## 4. Required common columns

For tenant-scoped application records:
- tenant_id (non-null);
- owner_user_id or service principal;
- created_at and updated_at in timestamptz;
- schema_version or payload_version for versioned JSON;
- retention_class;
- correlation identifiers where applicable.

For workflow state:
- state;
- state_version integer for optimistic concurrency;
- policy_version;
- plan_hash;
- deadline_at;
- aggregate counters and budget ceilings;
- terminal_reason_code.

For artifacts:
- storage_bucket and object_key;
- sha256;
- byte_size;
- detected_mime_type and declared_mime_type;
- scan_status;
- owner and access scope;
- expiration/retention time.

## 5. Security and RLS design

Do not assume RLS protects service_role. Supabase service-role access can bypass RLS. The application must select one of these reviewed patterns:

1. Prefer user JWT context plus explicit per-tenant RLS policies for user-owned rows, where request lifecycle and database connection handling safely preserve caller identity.
2. For backend service access, use a restricted database role without BYPASSRLS where supported, or enforce a formally tested server authorization layer and prevent browser access to the schema.
3. Keep service_role credentials server-side only. Never grant anon/authenticated direct access to privileged workflow, tool, provider, or audit tables.

For every table, test:
- user A cannot read/write user B records;
- tenant A cannot access tenant B;
- a service request cannot change tenant identity from client metadata;
- unauthenticated callers have zero access;
- privileged reviewer/admin operations are separately scoped and audited.

RLS policies must be designed per table and access pattern. Do not add a universal authenticated policy and do not disable RLS to make integrations work.

## 6. Audit event integrity

Audit records should be append-only to application roles. Events include:
- workflow accepted, state changed, cancelled, expired;
- authorization allow/deny;
- tool proposed, denied, approved, executed, failed;
- provider selected, fallback, circuit-open;
- evidence retrieved, blocked, citation verified/invalidated;
- artifact created, scanned, accessed, expired;
- policy/configuration version changed.

Do not write secrets, full source text, or unredacted request bodies into the audit stream. Store hashes and references when possible. Administrative corrections are new compensating events, never silent mutation of history.

## 7. Idempotency and concurrency

Idempotency scope includes principal/tenant, route, and hashed key. Store request hash and workflow/result ID. Reusing a key with a different request body returns a conflict. Concurrent duplicate requests resolve to one workflow, not duplicate side effects.

For state transitions, use compare-and-swap on state_version or equivalent guarded update. Workers claim work with leases and monotonically increasing fencing tokens. Expired leases may be reclaimed only when the worker's fencing token is no longer current.

## 8. Migration order

1. Create ugai schema only after security and exposure review.
2. Add owner/tenant tables and minimal RLS/grants.
3. Add workflow_runs and state transition audit.
4. Add workflow_steps and attempts.
5. Add idempotency and outbox/job records.
6. Add provider usage and tool invocation records.
7. Add artifacts registry.
8. Add dashboards and retention jobs.

Every migration has reviewed SQL and rollback/forward-recovery notes, schema diff, grants/RLS diff, integration tests using anon/authenticated/service roles, backup/restore plan, and performance checks for new indexes.

No migration to production is authorized by this specification.

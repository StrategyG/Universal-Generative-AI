# Cataran Platform Contracts v1.0.0

**Status:** PROPOSED — architecture review required; not yet a production contract  
**Canonical-home candidate:** `StrategyG/Universal-Generative-AI/contracts/v1/`  
**Contract authority:** Master Architect / Cataran Architecture Governance  
**Runtime owner:** UGAI owns reasoning, decisions, orchestration and authoritative task lifecycle  
**Consumers:** IM19, AI Notebook Studio, Cloudbrowser, RAG_Cerdas, Android Connector and REVORA IDE where approved  
**Effective date:** 2026-11-05  
**Compatibility policy:** Semantic Versioning; see §12

> This directory is a controlled transitional contract home inside the existing UGAI repository. It does not create an eighth repository. The schemas become normative only after Architecture Owner review and acceptance. Until then, consumers must not claim conformance.

## 1. Component ownership

| Component | Owns | Must not own |
|---|---|---|
| UGAI | Reasoning, decision policy, model routing, orchestration, authoritative task state, task event sequence, retry/reconciliation policy | MCP gateway implementation, client UI, connector secrets, browser execution |
| IM19 | The single MCP gateway, upstream MCP connection lifecycle, OAuth/provider credentials, tool authorization, connector policy, quotas, tool audit | Independent reasoning authority or a competing platform task state machine |
| AI Notebook Studio | User-facing notebook, workspace, session, client-side view of task state, user approval UX, upload UX | Authoritative orchestration or direct provider/tool credentials |
| Cloudbrowser | Isolated browser/media execution worker, worker leases, sandbox and execution artifacts | Decision authority, MCP gateway or direct unrestricted tool access |
| RAG_Cerdas | Document ingestion, extraction, indexing, hybrid retrieval, provenance and retrieval evaluation | Task orchestration, tool permission or autonomous side effects |
| Android Connector | Local/device adapter and Android-specific connector runtime, calling IM19 under delegated identity | A second central MCP gateway or independent tenant authority |
| REVORA IDE | Optional coding/editor module, consuming UGAI task and IM19 tool contracts; scope remains conditional | A duplicate orchestration plane or gateway |

**Ownership rule:** one accountable human maintainer per implementation task. AI agents may be lead executors or reviewers, but do not replace the accountable maintainer. Each shared contract/schema has one writer per change.

## 2. Trust and identity model

### 2.1 Principal

The durable external principal identity is the pair:

`principal = (issuer, subject)`

- `issuer` is the exact configured OIDC issuer identifier.
- `subject` is the opaque OIDC `sub` value. It is not globally unique by itself.
- `principal_id` is an internal stable identifier derived from a provisioned identity-link record; it is not a client-supplied substitute for issuer/subject.
- Email, display name, username, client-supplied role, and a bare subject are not authorization keys.

### 2.2 Tenant and project

- `tenant_id` and `project_id` are resolved and authorized server-side on every request.
- The client may request a tenant/project scope, but the server must validate active membership and resource access before acting.
- Supabase Auth `auth.users.id` is a distinct UUID identity. Map it explicitly to `(issuer, subject)` with a provisioned identity-link table. Never cast `sub` to UUID, match by email, or trust a role claim as proof of membership.
- Roles are namespaced and mapped centrally. Do not silently equate Notebook API roles, Supabase roles, OIDC scopes, IM19 tool permissions, and operating-system roles.

### 2.3 Service identity

Service-to-service calls use a verifiable workload identity and audience-bound short-lived credentials. A user identity and a service identity remain separate fields in the authorization context. A worker cannot elevate the originating user's permissions.

## 3. Common request and event envelope

All cross-service task, tool, worker, approval and evidence messages carry these correlation fields:

| Field | Type | Requirement |
|---|---|---|
| `contract_version` | string | Required; SemVer contract version such as `1.0.0` |
| `message_id` | UUID | Required; unique event/message ID |
| `message_type` | string | Required; namespaced event type |
| `occurred_at` | RFC 3339 UTC timestamp | Required |
| `tenant_id` | UUID/string identifier | Required; server-authorized tenant |
| `project_id` | UUID/string identifier or null | Required key; null only for tenant-wide operations |
| `principal` | object | Required actor context: issuer, subject, principal_id |
| `service_actor` | object or null | Workload identity when a service acts |
| `task_id` | UUID | Required for task-scoped messages |
| `correlation_id` | UUID | Required; stable across the end-to-end operation |
| `causation_id` | UUID or null | Parent message/event when applicable |
| `sequence` | positive integer | Monotonic per task stream; duplicate sequence is rejected or reconciled |
| `producer` | string | Required service name and version |
| `payload` | object | Message-specific schema; reject unknown security-sensitive fields |
| `trace_context` | object | W3C trace context where instrumentation is enabled |

Never put bearer tokens, OAuth refresh tokens, API keys, cookies, passwords, private prompts containing secrets, or raw secret values in events, logs, traces or evidence. Pass opaque vault references only, and only between authorized services.

## 4. Task contract and lifecycle

### 4.1 Authoritative ownership

UGAI is the sole authority for platform task lifecycle and task state transitions. Notebook displays a projection. IM19, Cloudbrowser, RAG_Cerdas and Android Connector own their local execution records, but cannot independently mark a platform task succeeded.

### 4.2 Required task attributes

A task includes at minimum:

- `task_id`, `tenant_id`, `project_id`, `requested_by` (principal), `task_type`
- `idempotency_key` and canonical `request_sha256`
- `contract_version`, `policy_version`, `created_at`, `updated_at`
- `state`, `attempt`, `deadline_at`, `priority`
- `correlation_id`, `last_event_sequence`
- `input_artifact_refs[]`, `output_artifact_refs[]`
- `approval_refs[]`, `evidence_refs[]`
- `error` (null unless failed/blocked/outcome unknown)

### 4.3 State vocabulary

`queued`, `running`, `awaiting_approval`, `succeeded`, `failed`, `cancelled`, `blocked`, `outcome_unknown`.

Terminal states are `succeeded`, `failed`, and `cancelled`. `blocked` requires an explicit unblock/resubmission decision. `outcome_unknown` requires reconciliation before any retry that could repeat an external side effect.

Allowed transitions:

- `queued → running | failed | cancelled | blocked`
- `running → awaiting_approval | succeeded | failed | cancelled | blocked | outcome_unknown`
- `awaiting_approval → running | blocked | cancelled`
- `outcome_unknown → succeeded | failed | blocked` (reconciliation only)
- `blocked → queued` only through an audited operator action or a new task attempt with a new idempotency key

All other transitions are rejected. A state change and its append-only event record must commit atomically.

### 4.4 Idempotency

The uniqueness scope is `(tenant_id, principal_id, idempotency_key)`.

- Same key + same canonical request digest: return the existing task and current state.
- Same key + different digest: return HTTP 409; do not mutate or reuse the prior task.
- Every worker attempt has a distinct attempt ID and fencing token.
- A stale worker lease/fencing token cannot commit a state transition or publish an artifact as current.
- Delivery is at-least-once; every consumer must be idempotent.

## 5. Approval and side-effect contract

An approval authorizes one immutable action, not a broad prompt or a future unspecified action.

An approval receipt binds:
- tenant, project, task and stage;
- exact action/tool name and target resource;
- canonical action payload SHA-256;
- policy version and requested permission scope;
- approver principal and authorization decision;
- issued/expiry timestamps, one-time nonce and decision;
- execution attempt/idempotency identity.

The service re-validates approver membership, role, tenant, expiry, nonce consumption and exact digest immediately before execution. Any changed payload, target, tool, policy-sensitive parameter or expired approval requires a new approval. A model-generated statement such as “approved” is never a receipt.

Read-only operations may use policy-based preauthorization only where explicitly configured. Writes, outbound messages, account changes, deletion, publishing, payments, external posting and destructive file changes require an explicit human approval path. Deny by default.

## 6. MCP and tool invocation — IM19 only

- IM19 is the only central MCP gateway for Cataran.
- UGAI sends a namespaced tool invocation request to IM19; it does not connect directly to upstream MCP servers or hold connector credentials.
- IM19 independently validates workload identity, originating principal context, tenant membership/authorization, tool allowlist, connector status, scopes, policy and egress destination.
- Tool invocation record contains `invocation_id`, `task_id`, `tenant_id`, `project_id`, connector ID/revision, tool name, input digest, approval receipt reference, deadline, attempt/fencing token and correlation IDs.
- IM19 returns a structured result with status, output artifact/evidence references, redacted error, effect certainty and audit reference.
- For an external side effect whose result is uncertain, IM19 returns `outcome_unknown`; do not blindly retry. Reconcile using a provider read-after-write/idempotency mechanism or operator intervention.
- SSRF controls: reject loopback, link-local, private, reserved and metadata-service addresses unless an explicitly approved internal destination rule permits them; revalidate DNS/IP at connection time; restrict redirects, ports, schemes and response sizes; enforce egress allowlists.

## 7. A2A and worker dispatch

A2A dispatch is a task-scoped service message, not a second task authority. It carries the common envelope, a narrowly scoped capability, attempt ID, lease expiry, fencing token, deadline and permitted artifact destinations.

- Cloudbrowser receives only the task data and tool/URL permissions necessary for its stage.
- Workers run in isolated, disposable environments with no ambient cloud metadata credentials, no host Docker socket and no unrestricted filesystem/network access.
- Worker output is untrusted until size/type/hash/schema and malware/content checks pass.
- A worker callback is evidence, not authority to mark the platform task complete. UGAI verifies lease, fencing token, expected stage, artifact hashes and acceptance predicates before transition.
- Callback retry is idempotent; expired lease callbacks are rejected.

## 8. RAG and evidence/provenance

RAG_Cerdas owns ingestion, extraction, chunking, indexing, hybrid retrieval, source lineage and retrieval evaluation. It does not own task orchestration or tool authorization.

Each evidence reference includes:
- `evidence_id`, `tenant_id`, `project_id`, source/artifact ID and source SHA-256;
- document version, page/section locator, chunk ID and chunk SHA-256;
- extraction/embedding model and version, ingestion timestamp and pipeline version;
- retrieval query ID, retrieval method, rank and score (with score semantics documented);
- access policy/classification and reviewer/label provenance when human-reviewed.

Evidence access is tenant/project scoped. A retrieved chunk is untrusted data, never an instruction or permission grant. Answer quality metrics are not reportable as validated until a human-reviewed, versioned gold set and independent evaluation run exist.

## 9. Notebook and Android client contract

- Notebook is the primary human interface and a projection of UGAI task state.
- Notebook submits tasks with an idempotency key, displays authoritative server state, renders approval requests and sends explicit user decisions.
- Client-side task state is never authoritative; refresh/reconnect rehydrates from UGAI.
- The Android Connector is a local/device adapter. It authenticates to IM19 using a delegated, scoped identity and reports local execution receipts. It does not mint tenant authority or expose a parallel public gateway as the platform MCP entry point.
- UI bundles and static health checks do not prove a live API connection. E2E acceptance requires a real authenticated session and server-side persisted task.

## 10. Error model

Every service returns a structured error:
- stable `code` (machine-readable, namespaced);
- `message` safe for the caller (no secrets/internal stack traces);
- `retryable` boolean;
- optional `retry_after_seconds`;
- `correlation_id`, `task_id`, `stage`, `attempt`;
- `details` restricted to validated, redacted, non-sensitive fields.

HTTP mappings: 400 invalid request/schema; 401 missing/invalid identity; 403 authorized identity lacks permission; 404 resource not visible to caller; 409 idempotency/transition/approval conflict; 422 semantically invalid action; 429 quota; 5xx service failure. Never return a cross-tenant existence signal.

## 11. Persistence, outbox and audit

- UGAI persists task state, append-only task events, idempotency reservations, approvals, outbox and reconciliation records transactionally.
- Outbox publish occurs after commit; consumers store processed message IDs and deduplicate.
- Audit records are append-only, tenant-scoped, access-controlled and tamper-evident; application logs are not the audit ledger.
- Every privileged decision and action is attributable to principal/service actor, policy version, code version and trace/correlation ID.
- Supabase remains the initially authoritative managed data plane until a separately approved PostgreSQL VM DR/replication and restore/failover/failback plan has passed. A backup copy is not a second writer.
- Google Drive is encrypted backup/archive, not a live transactional database or source of truth.

## 12. Versioning and compatibility policy

- Contract source is versioned under `contracts/v1/` in UGAI as a transitional canonical home; no eighth repository is created.
- Patch version: clarifications or non-semantic corrections.
- Minor version: backward-compatible additive fields, optional capabilities or new event types.
- Major version: removed/renamed fields, changed semantics, new required fields, state-machine incompatibility or authorization behavior changes.
- Consumers pin an exact contract version and schema digest. No implicit “latest”.
- Every consumer runs golden fixtures and compatibility tests against its pinned version.
- A major version requires a migration plan, parallel-read/dual-publish period where appropriate, consumer matrix, rollback path and Architecture Owner approval.
- No contract is called canonical/approved until the Architecture Owner records acceptance and the PR is merged to UGAI main.

## 13. Minimum conformance gates

A consumer is conformant only when CI proves:
1. schema validation for valid and invalid golden fixtures;
2. tenant/principal mismatch rejection and no cross-tenant resource disclosure;
3. idempotency replay and key/digest conflict behavior;
4. task transition allowlist and sequence monotonicity;
5. approval digest/expiry/nonce replay rejection;
6. worker lease expiry and stale fencing-token rejection;
7. outbox duplicate delivery and consumer idempotency;
8. structured errors with secret redaction;
9. artifact SHA-256 and provenance verification;
10. compatibility test against the exact pinned contract digest.

## 14. Consumer implementation map

| Consumer | First conformance responsibility | Current gap to close |
|---|---|---|
| UGAI | Authoritative task/event/approval implementation and published schemas | Clean integration base; converge PR #23/#31 without merging stacked history blindly |
| IM19 | MCP invocation, connector revision, policy/audit and effect certainty | Inject real tenant/secret resolvers and egress policy in isolated staging |
| AI Notebook Studio | Identity mapping, task submission/status projection and approval UI | Resolve principal→Supabase user mapping; persist and route task API; load UI bundle |
| Cloudbrowser | Signed worker dispatch, lease/fencing and artifact receipt | Replace single-owner pilot with tenant-isolated distributed worker |
| RAG_Cerdas | Evidence/provenance object and gold-set evaluator | Human-reviewed relevance labels and source-to-chunk lineage |
| Android Connector | Delegated device principal and signed adapter receipts | Persistence, real OAuth/OIDC staging and IM19-only remote gateway |
| REVORA IDE | Contract-pinned editor job and artifact interface, if retained | Main is bootstrap; evaluate feature branches before choosing IDE-only scope or freeze |

## 15. Release rule

This specification alone is not evidence of implementation. A PR, passing CI, or a local smoke test cannot authorize production. Production acceptance requires a staging end-to-end run across Notebook → UGAI → IM19 and at least one approved tool/worker/RAG path; independent negative security tests; production deployment evidence; monitoring/alert validation; backup restore and rollback drills; named on-call ownership; and Architecture Owner + independent QA sign-off.

# UGAI Durable Hybrid Workflow Engine — V1.1

**Implementation status:** candidate code is on \`feature/ugai-notebook-task-api-v1\`, stacked on the reasoning/runtime candidate branch. This is not merged to \`main\`, not deployed, and not production-ready. The SQL file remains a design/bootstrap blueprint, not a versioned Supabase migration. No live database has been changed.

## Responsibility boundaries

- UGAI owns task identity, tenant/workspace enforcement, state transitions, planning contracts, approval coordination, evidence digests and completion gates.
- Model providers return typed proposals only. Model output cannot write workflow state or choose unrestricted tools.
- IM19 remains the remote MCP transport and provider credential boundary. UGAI applies task-specific allowlists.
- PostgreSQL is the target durable store for task state, state versions, worker leases, idempotency keys, encrypted input payloads and append-only events. The blueprint is not yet applied.
- Hybrid workers share the same task store: local workers handle short bounded tasks; dedicated worker services handle long-running or isolated tasks. Worker identity and tool permissions remain separate.

## Notebook task API candidate

The current candidate exposes:

- \`POST /api/v1/tasks\` — accepts bounded user intent and immutable artifact references; requires \`X-Request-ID\` and \`Idempotency-Key\`.
- \`GET /api/v1/tasks/{task_id}\` — returns task state under actor, tenant and workspace checks.
- \`POST /api/v1/tasks/{task_id}/cancel\` — requests cancellation only when no worker lease is held; an active or uncertain lease returns a conflict and must be reconciled.

The request schema rejects client-supplied \`tenant_id\` and \`actor_id\`. Those values are derived from verified OIDC claims. Submission also requires a signed \`workspace_ids\` membership claim and the operation-specific OIDC scope:

| Operation | Required scope |
|---|---|
| Create task | \`ugai:tasks:write\` |
| Read status | \`ugai:tasks:read\` |
| Cancel task | \`ugai:tasks:cancel\` |

The trusted token broker must issue these claims only after checking active Studio membership and bind the requested workspace into the delegated token. That broker-side membership check and production identity configuration are not yet evidenced. UGAI keeps workspace membership separate from \`project_ids\`; it does not infer one identifier type from the other.

Task input is serialized to bounded JSON, SHA-256 digested and encrypted with AES-256-GCM before storage. Associated authenticated data binds the ciphertext to tenant ID, task ID and key version. Ciphertext is inserted atomically with the task row; plaintext is not written to task metadata or event rows. The current candidate supports a single configured 32-byte key version. KMS envelope encryption, key rotation/re-encryption, key recovery and retention/deletion policy remain production blockers.

The API is disabled by default. It returns \`503 TASK_SERVICE_DISABLED\` until a dedicated workflow database URL and valid payload key are configured. Production requires PostgreSQL \`verify-full\` TLS. The workflow database pool is distinct from the legacy generation queue.

**Worker limitation:** the candidate stores \`notebook.request\` tasks but does not yet register a production handler or deploy a worker for this task type. Accepted tasks therefore remain in \`received\` until that handler is implemented and deployed. The current API is a durable acceptance/status/cancel foundation, not a completed notebook execution path.

## State machine

~~~text
received -> observing -> planning -> executing -> verifying -> succeeded
awaiting_approval -> executing (verified receipt required)
awaiting_clarification -> observing (user response required)
failed -> received (explicitly safe retry; maximum two retries)
blocked -> observing (operator override required)
succeeded / cancelled -> terminal
~~~

The transition policy is deterministic and separate from model output. Every transition uses an expected version and a worker lease token. A transition clears the lease atomically so a capable worker can claim the next stage.

## Recovery and concurrency

- Claim uses PostgreSQL row locking with SKIP LOCKED inside a short transaction.
- Every claim issues a fresh random fencing token.
- Each store call sets a transaction-local tenant context; RLS predicates scope task, payload, event and artifact rows to that tenant. RLS is both enabled and forced so ordinary table owners are subject to policies (superusers and \`BYPASSRLS\` roles remain privileged and must never be used by workers).
- Heartbeat and transition require the tenant, worker ID, token, and unexpired lease to match.
- State update and event append commit in one transaction.
- Encrypted task payload insertion commits atomically with task creation. An idempotency replay returns the original task and does not create a second payload row.
- A crashed worker leaves the last durable state. A new worker can reclaim the task after lease expiry.
- Explicitly retryable failures receive bounded exponential backoff (30 seconds base, 1 hour cap); a scheduler requeues only due rows using SKIP LOCKED, tenant context, retry budget and version checks.
- Cancellation is fenced by an optimistic version and rejects a task while any worker lease is present. A lost response or expired lease requires reconciliation, not blind retry.
- Unknown external outcomes remain blocked for reconciliation. Lease expiry does not prove an external action failed.

## Security and evidence

- OIDC signature, issuer, audience, subject and tenant are verified before a principal is created.
- Task routes require an exact delegated scope as well as an authorized role.
- Workspace access is checked against a separate signed \`workspace_ids\` claim; a general role or \`project_ids\` entry is not substituted.
- The service request body cannot choose its actor or tenant.
- Task metadata and event details use explicit allowlists. User intent is encrypted and not logged as task metadata.
- The workflow runtime role is separate from the database owner and public client roles; RLS is forced and payload rows are append-only.
- Model self-critique cannot mark a task verified. A task reaches succeeded only after external completion gates pass and evidence is recorded.
- Append-only events protect against ordinary application mutation; stronger evidence retention needs external signed checkpoints or WORM storage.

## Required configuration (candidate branch)

| Setting | Purpose |
|---|---|
| \`WORKFLOW_TASKS_ENABLED\` | Explicit opt-in; default false |
| \`WORKFLOW_DATABASE_URL\` | Dedicated database connection for durable tasks |
| \`WORKFLOW_DATABASE_SSL_MODE\` | Production must be \`verify-full\` |
| \`TASK_PAYLOAD_ENCRYPTION_KEY\` | Base64-encoded 32-byte AES key; source from approved secret manager |
| \`TASK_PAYLOAD_KEY_VERSION\` | Key version label for ciphertext AAD |
| \`AUTH_MODE=oidc\` | Required in production |
| \`OIDC_ISSUER\`, \`OIDC_AUDIENCE\`, \`OIDC_JWKS_URL\` | Verified token configuration |
| \`OIDC_SCOPES_CLAIM\` | Delegated operation scopes; default \`scope\` |
| \`OIDC_WORKSPACES_CLAIM\` | Signed workspace membership list; default \`workspace_ids\` |

Do not place secrets in environment files committed to source control. Runtime values must come from an approved secret manager.

## Deployment prerequisites

1. Convert the schema blueprint into a numbered, reviewed migration with an explicit rollback/forward-fix strategy. Do not run the blueprint directly against production.
2. Apply to an isolated Supabase development branch first, then staging. Verify existing-schema upgrade as well as fresh creation.
3. Create a dedicated database login and grant membership in \`ugai_workflow_runtime\`. Do not connect API workers as the database owner, Supabase \`service_role\`, or any \`BYPASSRLS\` role.
4. Keep the workflow schema outside exposed Data API schemas. Do not grant \`anon\` or \`authenticated\` access.
5. Implement and test the trusted token broker: active membership, issuer, audience, short token lifetime, exact scopes, tenant and workspace claims, revocation and service-to-service authentication.
6. Implement a dedicated \`notebook.request\` worker handler, encrypted result persistence, artifact/result retrieval and approval callbacks.
7. Move payload encryption to KMS-backed envelope encryption with key rotation and recovery.
8. Run unit, PostgreSQL RLS/concurrency, contract, cross-repository E2E, penetration, load, backup/restore and crash-recovery tests before production.

## Acceptance tests

- Concurrent workers cannot hold the same live lease.
- A stale worker cannot heartbeat or transition after lease replacement.
- Cross-tenant and cross-workspace task reads, payload reads, claims, heartbeats and transitions are denied.
- A stale task version is rejected without appending an event.
- An idempotency key cannot be reused with a different actor, task type, workspace or payload digest.
- A repeated identical submission returns the original task and stores one payload row only.
- Ciphertext cannot be decrypted under a different tenant, task ID or key version.
- Cancellation cannot revoke an active worker lease.
- Unapproved execution, missing clarification, blind retry, terminal-state edits and unapproved blocked recovery are rejected.
- State updates and event records are atomic.
- RLS and grants deny public client roles while the dedicated runtime role has least privilege.
- The release gate cannot report success without test evidence tied to the current task version and plan digest.

# UGAI durable task API — production configuration and activation runbook

**Status:** implementation guide for draft PR #38. This is not a deployment record. Task acceptance remains disabled until the activation gates below are independently verified.

## 1. Security invariants

- User identity is derived from a signature-verified OIDC token, including its issuer.
- Tenant, actor and project authorization must be checked on every API request.
- A workspace identifier supplied by a client is not, by itself, authorization for a UGAI project.
- Task metadata contains only opaque references, digests, project ID, schema version and correlation ID. Never persist raw prompts, credentials, provider tokens or hidden reasoning in task rows, events, traces or logs.
- Task input is encrypted with AES-256-GCM before persistence. The encryption keys are provided by the deployment secret manager, not PostgreSQL or Git.
- Runtime PostgreSQL connections must use a dedicated login that is a member of `ugai_workflow_runtime`, is not a superuser, does not have `BYPASSRLS`, and does not own the schema/tables.
- IM19 remains the only MCP gateway. UGAI does not directly expose its own competing MCP server.
- Human approval remains mandatory for high-impact/external actions.

## 2. Environment settings

Use the deployment's secret manager for secrets. Do not put actual values in repository files, notebook cells, CI logs or issue comments.

| Setting | Purpose | Required state |
|---|---|---|
| `UGAI_WORKFLOW_DATABASE_URL` | Dedicated PostgreSQL login DSN | PostgreSQL URL; production requires exactly `sslmode=verify-full` |
| `UGAI_WORKFLOW_INPUT_KEYRING_JSON` | JSON object of key ID → base64 AES key | Each decoded key must be exactly 32 bytes |
| `UGAI_WORKFLOW_INPUT_ACTIVE_KEY_ID` | Active key version | Must exist in keyring |
| `UGAI_WORKFLOW_TASK_ACCEPTANCE_ENABLED` | Enables POST input/task intake | `false` until all activation gates pass |
| `UGAI_WORKFLOW_ENABLED_TASK_TYPES` | Explicit task-type allowlist | Empty until handlers are reviewed and registered |

Key rotation must preserve old decryption keys for the full retention window or until all records encrypted by that key are re-encrypted/expired under a reviewed process. Key IDs are version labels, not key material.

## 3. PostgreSQL deployment order

Use the approved migration runner and a privileged migration operator, not the application runtime login.

1. Apply `postgres/migrations/0003_ugai_workflow_runtime.sql`.
2. Create a dedicated LOGIN role with a strong secret, grant membership in `ugai_workflow_runtime`, and do not grant superuser, `BYPASSRLS`, schema ownership or table ownership.
3. Apply `postgres/migrations/0004_ugai_workflow_encrypted_inputs.sql`.
4. Verify schema/table grants and RLS policies.
5. Start one staging API instance with task acceptance disabled. Confirm startup's database-role assertion passes.
6. Run migrations and tests against PostgreSQL 16+ staging before production approval.

Never run these migrations manually in a production SQL editor without an approved change record, current backup and rollback/recovery plan.

## 4. Required database-role checks

The application startup validates the connected database role. A staging operator must additionally verify:

- `current_user` is a non-owner login.
- `pg_roles.rolsuper = false`.
- `pg_roles.rolbypassrls = false`.
- It is a member of `ugai_workflow_runtime`.
- It has only the grants needed by the current store/vault implementation.
- Tenant and actor RLS tests pass under the actual application login, not only the migration owner.

Do not fix permission failures by granting broad UPDATE/DELETE or owner privileges to the runtime login. Fix the SQL operation or narrowly scoped privilege only after security review.

## 5. Activation gates — all required

Task acceptance may be enabled only after all conditions below are recorded against exact commits and the staging environment:

1. Canonical Platform Contracts and task-state projection are approved; the competing UGAI contract candidates have been reconciled.
2. Notebook's workspace → UGAI project mapping is resolved server-side and tested. The client cannot assert tenant, actor or project authority.
3. A production-registered handler exists for every enabled task type. It uses approved evidence sources through IM19, a trusted plan builder, an append-only audit sink, an approval gateway, and a concrete encrypted/idempotent result store.
4. The worker process has readiness/liveness, capacity/lease configuration, restart persistence tests, retry/reconciliation controls and independent service identity.
5. Human-approval receipt verification and execution are proven end-to-end. API cancellation must not revoke or overwrite a worker lease while an external side effect may be in flight.
6. Input and result retention, expiry purge, key rotation, encryption-key recovery and data-deletion policy are implemented and verified.
7. Tenant/actor isolation, cross-tenant and cross-project negative tests, contract tests, API tests, PostgreSQL RLS tests, dependency audit, CodeQL/security scans and independent QA pass on the exact release SHA.
8. Notebook → UGAI → worker → IM19/RAG/Cloudbrowser → UGAI → Notebook staging E2E passes, including API restart, retry, cancellation race, approval, failure recovery and artifact result retrieval.
9. Backup/restore, monitoring, alerting, tracing, resource/cost controls, rollback and RTO/RPO are demonstrated in staging.
10. Agent 08 (independent QA) signs off; deployment has a reviewed release record and a designated human approver.

Until then, keep `UGAI_WORKFLOW_TASK_ACCEPTANCE_ENABLED=false` and do not add task types to the allowlist.

## 6. Current implementation boundary

PR #38 currently adds the encrypted input vault, PostgreSQL migration, guarded task input/submit/status/cancel API, startup role assertion, state projection and tests.

It does **not** yet deliver a concrete registered decision worker, workspace/project resolver, result retrieval API, encrypted result store, retention purge process, complete approval lifecycle API, staging deployment or end-to-end integration. Do not claim production readiness or enable task intake based solely on green CI.

## 7. Incident response

- If role assertion, RLS or keyring configuration fails, fail startup/readiness. Do not fall back to in-memory task persistence or an owner database connection.
- If decryption fails, return an opaque operational error, record non-secret correlation metadata and stop processing the affected task. Never log plaintext.
- If a worker lease or external execution result is uncertain, mark/reconcile the outcome through the durable workflow process. Do not blindly repeat external side effects.
- If the keyring is unavailable, do not accept new inputs or rotate to an unknown key.
- Roll back the application release only to a version compatible with the deployed schema. Do not remove the encrypted-input table or weaken RLS as an emergency workaround.

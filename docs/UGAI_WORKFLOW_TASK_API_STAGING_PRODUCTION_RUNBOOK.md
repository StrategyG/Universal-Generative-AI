# UGAI Notebook Task API — Staging and Production Runbook

## Scope and release status

This runbook covers the first durable Notebook reasoning slice only:
- authenticated, tenant/project-scoped task intake;
- encrypted task input and result storage using AES-256-GCM;
- one dedicated worker per configured tenant;
- read-only text reasoning with an independent evaluator;
- append-only lifecycle events and lease fencing.

It does **not** enable notebook code execution, artifact retrieval, MCP tools, Cloudbrowser dispatch, or automatic approval. Every returned candidate is marked `human_review_required=true`.

This PR is not a production deployment. Keep `workflow_task_acceptance_enabled=false` until all staging gates below pass and the Architecture Owner and independent QA explicitly accept the release.

## 1. Pre-deployment ownership and controls

Before staging:
1. Protect the target branch and require reviewed pull requests, required CI, CODEOWNERS and deployment approval.
2. Confirm the accepted canonical Platform Contracts version and its consumer mapping.
3. Confirm the API and dedicated worker are built from the same immutable commit/tag.
4. Use separate database logins for migrations and runtime. The API/worker runtime login must be a member of `ugai_workflow_runtime`, not a schema/table owner, not a superuser and not `BYPASSRLS`.
5. Provision OIDC issuer, audience, JWKS and claim mapping through the approved identity provider. Do not accept actor or tenant IDs from request bodies.
6. Assign an operator who can provision the read-only workspace binding registry from the authoritative Notebook/project system.

## 2. Database rollout

Back up the target database and prove restore before applying migrations. Apply reviewed migrations in this order:

1. `0003_ugai_workflow_runtime.sql` — durable tasks, state/events, lease fencing and RLS.
2. `0004_ugai_workflow_encrypted_inputs.sql` — encrypted input vault.
3. `0005_ugai_workflow_encrypted_results.sql` — immutable encrypted result vault.
4. `0006_ugai_workflow_worker_registry.sql` — tenant-scoped worker capabilities and heartbeats.
5. `0007_ugai_workflow_workspace_bindings.sql` — authoritative workspace-to-project bindings.

The runtime role must have only the grants required by the runtime assertion:
- schema usage;
- task select/insert and constrained update;
- event select/insert;
- input select/insert;
- result select/insert;
- worker select/insert/update;
- workspace binding select.

It must not own these tables or bypass RLS. The application sets transaction-local `app.ugai_tenant_id` and, for input/result vault access, `app.ugai_actor_id`.

### Workspace bindings

The runtime role is deliberately read-only on `workspace_bindings`. A trusted workspace integration or operator-owned provisioning process must insert the exact mapping after verifying it from the authoritative source:
- tenant ID;
- workspace UUID;
- project ID;
- active/revoked status.

Do not accept a workspace UUID as proof of ownership. Do not use wildcard, email-based inference or client-supplied tenant/project overrides. Revocation must mark the binding `revoked`; new input/task submissions then fail closed.

## 3. Encryption key configuration

Set:
- `UGAI_WORKFLOW_DATABASE_URL` to the restricted runtime login DSN;
- in production, exactly one `sslmode=verify-full` and a valid CA trust chain;
- `UGAI_WORKFLOW_INPUT_KEYRING_JSON` to a JSON object of key IDs and base64-encoded 32-byte keys;
- `UGAI_WORKFLOW_INPUT_ACTIVE_KEY_ID` to one key ID present in that keyring.

Keep keys in the approved secret manager. Never commit, log, or expose them to the client. Retain old key versions while rows encrypted under those versions exist. Test rotation and decryptability using a disposable staging copy before retiring any key. A database restore without the matching keyring is not a successful recovery.

## 4. OIDC and API configuration

Configure at minimum:
- `AUTH_MODE=oidc`;
- `OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_JWKS_URL`;
- tenant, roles and project claim names;
- `UGAI_WORKFLOW_ENABLED_TASK_TYPES=notebook_request`.

The API derives its stable actor key from the verified `(issuer, subject)` pair. The original subject is not used as a cross-issuer identifier.

Initially set:
- `UGAI_WORKFLOW_TASK_ACCEPTANCE_ENABLED=false`.

Start the API and verify:
- readiness rejects missing/invalid OIDC configuration;
- invalid issuer, audience, signature, expiry or tenant claim is denied;
- project access alone is not sufficient without an active workspace/project binding;
- task submission is rejected while no fresh registered worker exists;
- non-owners cannot cancel or retrieve another actor's result;
- a result is not returned before the task reaches `SUCCEEDED`.

## 5. Dedicated worker configuration

Deploy the worker as a separate process/container, not in the API request process:
- `UGAI_WORKFLOW_WORKER_ENABLED=true`;
- `UGAI_WORKFLOW_WORKER_ID` set to a unique stable process ID;
- `UGAI_WORKFLOW_WORKER_TENANT_ID` set to one exact tenant;
- `UGAI_WORKFLOW_WORKER_POLL_SECONDS` bounded (default 2 seconds);
- `UGAI_WORKFLOW_WORKER_LEASE_SECONDS` bounded (default 45 seconds);
- `UGAI_WORKFLOW_WORKER_HEARTBEAT_SECONDS` below half the lease (default 12 seconds).

Start with:
```bash
python -m app.notebook_worker
```

The process registers only `notebook_request` for its configured tenant and refreshes its registry heartbeat every 15 seconds. API intake requires a matching active worker heartbeat no older than 60 seconds. A crashed or disconnected worker therefore stops new intake after the freshness window.

This first worker is intentionally single-tenant per process. Do not configure a wildcard tenant. Multi-tenant scheduling requires a separately reviewed tenant resolver and deployment topology.

## 6. Safe activation order

1. Apply and verify all five migrations in staging.
2. Verify restricted-role assertions using the exact API/worker runtime login.
3. Provision one approved workspace binding from the authoritative workspace/project system.
4. Deploy API with task acceptance disabled.
5. Start the worker with the exact tenant and allowed task type.
6. Confirm the worker row is active and its heartbeat advances.
7. Submit one synthetic task with a synthetic project/workspace and a fresh idempotency key.
8. Confirm encrypted input/result are stored, no plaintext is stored in workflow tables, the task transitions through the expected states, and its result requires human review.
9. Kill the worker during a test execution. Confirm an expired `executing` lease moves to `outcome_unknown`, an append-only event is recorded, and a second worker does not blindly replay the model call.
10. Confirm the reconciler advances only when a valid encrypted result already exists and its authenticated digest matches.
11. Test cancellation, cross-tenant reads, cross-actor reads, revoked workspace binding, stale worker heartbeat and idempotency conflicts.
12. Only after independent QA and human release approval, set `UGAI_WORKFLOW_TASK_ACCEPTANCE_ENABLED=true` on the API deployment.

## 7. API lifecycle

- `POST /api/v1/task-inputs`: validates an active workspace/project binding and stores the input encrypted.
- `POST /api/v1/tasks`: verifies input actor, tenant, project and digest; requires an enabled task type and fresh worker heartbeat; inserts a durable task idempotently.
- `GET /api/v1/tasks/{task_id}`: tenant/project-scoped status.
- `POST /api/v1/tasks/{task_id}/cancel`: owner or tenant/platform admin only; leased or state-changing tasks return conflict.
- `GET /api/v1/tasks/{task_id}/result`: owner/admin only and only after `SUCCEEDED`; decrypts and verifies the immutable result.

The Notebook reasoning handler supports only reasoning/analysis text tasks. Any requested capability outside that allowlist or any artifact reference is blocked. It does not execute code, call MCP, invoke Cloudbrowser or perform external writes.

## 8. Monitoring and alerts

Alert on:
- no active worker heartbeat for a tenant with acceptance enabled;
- worker restart/lease loss or `outcome_unknown` count increase;
- workspace binding lookup errors or revoked binding attempts;
- PostgreSQL pool exhaustion, RLS/permission errors or migration drift;
- encryption-key lookup/authentication/digest failures;
- provider error, independent evaluator failure, route rejection or cost-budget rejection;
- task age by state, queue depth, retries and cancellation conflicts.

Logs must contain request/task correlation identifiers and bounded error codes only. Never log task intent, plaintext inputs, candidate answers, model reasoning, access tokens, encryption keys or raw connector responses.

## 9. Rollback and recovery

- Stop new intake first by setting task acceptance to false.
- Allow in-flight leased work to finish or expire; reconcile `outcome_unknown` only from an existing verified encrypted result.
- Stop the worker and confirm its registry row is stopped or heartbeat has aged out.
- Do not delete workflow inputs, results, events or workspace mappings as part of a code rollback.
- Keep migrations 0003–0007 in place during application rollback; do not downgrade state constraints while any task uses `outcome_unknown`.
- Restore database and matching keyring together, then prove decryptability and digest integrity before reopening intake.
- Re-run the full staging acceptance suite after restoring or changing the database, keyring, OIDC issuer or worker deployment.

## 10. Production acceptance checklist

Production remains NO-GO until all items have exact-SHA and environment evidence:
- branch protections/rulesets and human review;
- accepted canonical platform contract and consumer compatibility;
- staging deployment of API and worker with approved secrets;
- live OIDC issuer/audience/JWKS and tenant/project/workspace provisioning;
- encrypted database migration, role/RLS tests and key rotation;
- worker crash/restart/lease fencing and outcome reconciliation tests;
- cross-tenant and cross-actor security tests;
- load, rate-limit, provider budget and failure-mode tests;
- backup restore and key recovery, rollback drill and monitoring/alerting;
- independent QA sign-off and authorized production release.

A passing GitHub Actions workflow is branch verification, not deployment evidence.

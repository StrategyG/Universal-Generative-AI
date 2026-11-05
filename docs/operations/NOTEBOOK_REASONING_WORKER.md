# UGAI Notebook reasoning worker

Status: implementation candidate. This document is not a deployment authorization.

## Scope of the first slice

The worker handles only the `notebook_task` task type and only the
`reasoning:read` capability. It:

- reads encrypted task input from the workflow database;
- validates tenant, project, workspace, capability and payload integrity;
- uses the approved model registry and policy-routed reasoning executor;
- requires an independent evaluator for the high-risk/deep profile;
- stores the candidate and independent critique as immutable encrypted output;
- marks the workflow task successful only after decrypting and checking the persisted
  result contract.

A successful workflow means that generation and persistence completed. It does **not**
mean that a human approved the answer. Every result remains
`verification_status=needs_human_review` and `human_review_required=true`.

The first slice does not execute notebook code, fetch uploaded artifacts, call IM19/MCP,
write to the workspace, deploy, publish, delete, or perform external actions.

## Required database separation

The API and worker must use different PostgreSQL logins.

- API: `WORKFLOW_DATABASE_URL`, whose login is a non-owner, non-superuser member
  of `ugai_workflow_runtime` and has no `BYPASSRLS`.
- Worker: `WORKFLOW_WORKER_DATABASE_URL`, whose login is a non-owner,
  non-superuser member of `ugai_workflow_worker`, is not a member of
  `ugai_workflow_runtime`, and has no `BYPASSRLS`.

Migration `0006_ugai_notebook_worker_results.sql` creates the non-login worker group,
RLS policies and minimum table grants. After it has been reviewed and successfully
applied in an isolated staging database, provision a login through the approved
secret-management workflow and grant it membership:

```sql
CREATE ROLE ugai_notebook_worker LOGIN NOBYPASSRLS;
GRANT ugai_workflow_worker TO ugai_notebook_worker;
```

Set the password out-of-band. Never put a password in a migration, repository, ticket,
container image, log, or chat. Do not grant this login membership in
`ugai_workflow_runtime`, table ownership, superuser, or `BYPASSRLS`.

## Runtime configuration

The API and worker deployment must share the same active and previous input-encryption
key ring. The keys are provisioned through the deployment secret manager.

| Setting | API | Worker |
|---|---|---|
| `WORKFLOW_TASK_API_ENABLED` | `true` | `true` |
| `WORKFLOW_DATABASE_URL` | API-only database login | Not used for worker DB access |
| `WORKFLOW_PAYLOAD_ENCRYPTION_KEY` | Required | Same key |
| `WORKFLOW_PAYLOAD_KEY_ID` | Required | Same key ID |
| `WORKFLOW_PAYLOAD_PREVIOUS_KEYS_JSON` | During key rotation | Same previous key ring |
| `WORKFLOW_WORKER_ENABLED` | Not required | `true` |
| `WORKFLOW_WORKER_DATABASE_URL` | Not used | Worker-only database login |
| `WORKFLOW_WORKER_TENANT_ID` | Not required | Explicit tenant scope |
| `WORKFLOW_WORKER_ID` | Not required | Unique per worker instance |
| `WORKFLOW_WORKER_POLL_SECONDS` | Not required | Defaults to 2 seconds |
| `WORKFLOW_WORKER_LEASE_SECONDS` | Not required | Defaults to 60 seconds |
| `WORKFLOW_WORKER_HEARTBEAT_SECONDS` | Not required | Defaults to 10 seconds |
| `REASONING_ROUTE_CATALOG_JSON` | Approved route catalog | Same approved catalog |
| `REASONING_PERMITTED_DATA_REGIONS` | Policy | Same policy |
| `REASONING_MAX_ESTIMATED_COST` | Policy | Same policy |

For production, both database URLs must use exactly one `sslmode=verify-full`.
The worker login must be distinct from the API login. The worker will refuse startup
when the role checks or required settings fail.

Run the worker as a separate supervised service:

```sh
python -m app.notebook_worker
```

Do not start it inside the API web process. Use one unique
`WORKFLOW_WORKER_ID` for each replica. The process handles SIGINT/SIGTERM, refreshes
a tenant-scoped heartbeat, stops claiming work after heartbeat registration fails,
and marks the registry entry inactive on graceful shutdown.

## Intake and readiness contract

The task API checks for an active worker heartbeat for the authenticated tenant and
`notebook_task` before accepting a new request. A missing/stale worker or unavailable
registry returns HTTP 503 and does not persist a new task. Worker heartbeats expire
after the API's 60-second freshness window.

The worker only accepts exactly `reasoning:read` and rejects non-empty artifact
references. Do not broaden this allowlist without a separately reviewed capability
contract and security tests.

## Result and reconciliation contract

Results are encrypted using the configured key ring and stored in
`ugai_workflow.task_results`. The database restricts inserts to the worker role and
makes rows immutable. The API role can read only under the current tenant setting;
the API endpoint also verifies task state and project membership before decrypting.

A worker that persists a result but loses its lease before state transition can be
recovered: the background reconciler verifies the already-persisted ciphertext digest
and task/project identity, then uses the evidence digest to transition
`outcome_unknown → verifying`. An unknown external outcome without a persisted
verified result remains quarantined; it is never replayed automatically.

The result endpoint is:

`GET /api/v1/tasks/{task_id}/result`

It returns only after task state is `succeeded`. The result still reports
`needs_human_review`; a separate, authenticated human review/approval workflow is
required before any downstream side effect may be authorized.

## Staging release gates

Before enabling this worker in any production environment:

1. Review migration 0006 and apply it only to a disposable or approved staging clone.
2. Prove the API and worker logins are distinct and satisfy the role checks.
3. Prove the API cannot write worker heartbeats or task results.
4. Prove worker cross-tenant reads and writes are denied by PostgreSQL RLS.
5. Prove no healthy worker means task intake returns 503 without a task row.
6. Run the end-to-end flow with an approved primary and independent evaluator route.
7. Verify result retrieval, project-membership denial, immutable result conflict and key rotation.
8. Restart the worker during execution; prove uncertain outcomes are quarantined, and only an already-persisted valid result is reconciled.
9. Verify the observability, alerting, process supervision, secrets, backup/restore and rollback plan.
10. Obtain independent Agent 08 QA and Agent 01 release approval.

CI against a disposable PostgreSQL service is not evidence of staging deployment, live
provider connectivity, human review, backup restoration, or production readiness.

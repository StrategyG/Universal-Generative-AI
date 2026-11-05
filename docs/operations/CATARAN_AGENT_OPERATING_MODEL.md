# Cataran Agent Operating Model — v1

**Status:** Proposed operational contract. It becomes active only after the workflow PRs are reviewed/merged, the worker is deployed, GitHub App permissions are verified, and branch rulesets are enforced.

## 1. Non-negotiable operating loop

Every scheduled cycle performs an organization-level audit and repository-level work selection:

1. **Discover:** read the default-branch SHA, open issues/PRs, review threads, workflow runs/check conclusions, security alerts and repository-specific acceptance documents.
2. **Analyze:** inspect relevant source, tests, dependency graph, architecture and recent changes. Cite exact paths and SHAs.
3. **Evaluate:** classify findings as P0/P1/P2/P3, identify root cause, affected repositories, risk, owner and dependencies.
4. **Plan:** create or update a durable GitHub issue/task record with one accountable implementation owner, exact acceptance criteria and a task branch.
5. **Implement:** change only the owned paths in the assigned task branch. Never write directly to the default branch.
6. **Test:** run focused tests first, then all relevant repository checks, contract/integration/security/regression tests.
7. **Verify:** attach exact commit SHA, CI run URLs, test counts and outcomes, review results, migration/rollback evidence and staging trace where relevant.
8. **Continue:** if incomplete at the next hourly checkpoint, resume from the durable task record and last verified checkpoint. Do not restart blindly or mark it done. When an agent completes its assigned task, the scheduler may assign the highest-priority unblocked task within that agent's ownership.
9. **Independent audit:** Agent 01 rechecks implementation evidence and cross-repository impact. It must not certify its own implementation.
10. **Stop:** stop the recurring engineering loop only after Agent 01 signs an independent 90–100/100 assessment AND every mandatory release gate in section 5 is satisfied. Otherwise status remains NO-GO and work continues.

One hour is a checkpoint cadence, not a work deadline or a worker execution time limit.

## 2. Role and authority matrix

| Agent | Role | Primary write ownership | Read scope | Mandatory exclusions |
|---|---|---|---|---|
| 01 | Independent Production Auditor | None; read-only | All seven Cataran repositories and attached CI/evidence | No code/issue/PR/settings writes; cannot approve own work; cannot waive gates |
| 02 | UGAI Principal AI Engineer | Universal-Generative-AI: reasoning, provider routing, decision runtime, workflow orchestration and UGAI tests | All repos for dependencies | No second MCP gateway; no direct IM19/Notebook implementation without a separate task owner |
| 03 | Architecture & Governance Principal | Universal-Generative-AI canonical ADRs, schemas/contracts and ownership/compatibility policy | All seven repos | One contract writer at a time; breaking changes require explicit Master Architect or named human-owner approval; Agent 03 cannot self-approve a breaking change |
| 04 | AI Notebook Principal Engineer | ai-notebook-studio-v: client, API, UX, workspace, notebook and app-side execution boundary | All repos for interface dependencies | No backend reasoning engine, no second MCP gateway, no tenant/identity bypass |
| 05 | Database & Knowledge Principal Engineer | RAG_Cerdas: ingestion/retrieval/evaluation; UGAI: approved database/knowledge adapters and migrations owned by UGAI | All repos for data contracts | No production database writes/cutover, fabricated labels/reviewers, destructive migrations or unapproved RAG publication |
| 06 | Software Engineering Principal | Only the repository and file/path set explicitly recorded in its assigned task | All repos needed for assigned task | No concurrent ownership of the same paths; no unilateral contract, security-policy or infrastructure changes |
| 07 | DevOps & Infrastructure Principal | CI/CD, workflow, container, deployment manifests, observability and runbooks across seven repos | All repos and deployment evidence | No secrets read/exfiltration, environment/ruleset administration, production deployment or infrastructure mutation without human approval |
| 08 | QA, Security & Reliability Principal | Tests, test harnesses, security checks and remediation code explicitly assigned across seven repos | All repos, workflow results and threat-model evidence | Cannot self-approve/self-certify; no live penetration/destructive tests; no risk acceptance on behalf of owner |
| 09 | System Integration & Optimization Principal | Cross-repo adapters, compatibility suites, end-to-end fixtures and integration fixes under an approved contract | All seven repos | No duplicate orchestration/MCP/database authority; contract changes require Agent 03 review and named owner |

### Repository write routing

- `Universal-Generative-AI`: Agent 02 and Agent 03 are primary owners. Agents 05/06/07/08/09 may write only when the issue names them as the single owner for a specific path set.
- `im19-universal-mcp`: Agent 06/07/08/09 may own assigned MCP gateway, deployment, test or integration paths; Agent 03 reviews contract impact. Agent 02 is read-only here unless separately assigned a UGAI-owned adapter change.
- `ai-notebook-studio-v`: Agent 04 is primary owner. Agents 06/07/08/09 may own explicitly separated tasks; Agent 03 reviews cross-plane contract changes.
- `RAG_Cerdas`: Agent 05 is primary owner. Agents 06/07/08/09 may own separated implementation/infra/test/integration tasks.
- `Cloudbrowser`: Agent 06/07/08/09 may own explicitly assigned worker/runtime/infra/test/integration paths; Agent 09 owns cross-plane compatibility only.
- `android-ai-universal-connector`: Agent 06/07/08/09 may own explicitly assigned adapter/device/infra/test/integration paths. IM19 remains the sole general MCP gateway for UGAI-originated tools.
- `REVORA_IDE`: frozen as non-critical-path until Agent 03 records an approved scope, accountable maintainer and security boundary. Only audit, documentation, or explicitly approved compatibility work may proceed.

All agents may read all seven repos when needed for dependency analysis. Read access does not imply write ownership.

## 3. Assignment and task contract

Every implementation task must carry:
- unique task ID and GitHub issue URL;
- exactly one implementation owner (Agent ID) and optional named reviewers;
- repository, base SHA, task branch and allowed file/path ownership;
- objective, root-cause hypothesis and affected dependency map;
- acceptance criteria and explicit non-goals;
- priority and blocked-by dependencies;
- test commands, security impact and rollback plan;
- checkpoint state, latest verified SHA and next action.

No two agents may write the same file or shared contract concurrently. Cross-repository work is a dependency graph of individually owned tasks, not a multi-writer free-for-all. Agent 03 may draft and maintain the canonical contract, but a breaking contract/version change requires explicit approval from the Master Architect or named human owner before consumer implementation or rollout.

## 4. Status and evidence rules

Use only these states:
- `NOT_STARTED`
- `IN_PROGRESS`
- `BLOCKED`
- `IMPLEMENTED` — code exists on a task branch/PR; tests may still be incomplete.
- `VERIFIED` — acceptance tests passed on the exact proposed SHA and required independent review passed.
- `DEPLOYED` — an approved environment shows the exact deployed image/config/schema digest and post-deploy smoke tests passed.

A merged PR, green unit test, README statement, local run or agent self-report alone does not prove production readiness. Never call a candidate deployed if it has not been deployed to the named environment.

Every verification record must include exact repository/branch/SHA, PR, workflow run URL, test counts (passed/failed/skipped), security results, reviewer, and staging/deployment evidence where applicable.

## 5. Mandatory production stop gates

Agent 01 may issue a 90–100/100 score and stop the loop only if all applicable mandatory gates pass:
1. No unresolved P0 issue and no unaccepted critical/high security finding.
2. Canonical versioned contracts and compatibility tests pass across all active planes.
3. Verified identity, issuer/subject mapping, tenant membership and cross-tenant denial tests pass.
4. Durable task lifecycle, outbox, idempotency, leases/fencing, cancellation, retry and unknown-outcome reconciliation pass.
5. IM19 is the sole governed MCP gateway; real non-production OAuth/provider boundary and SSRF/egress/tenant/audit checks pass.
6. Notebook authorization, packaged UI, workspace and isolated execution acceptance pass.
7. RAG metrics use reviewed, provenance-backed gold labels; no fabricated labels/reviewers or unsupported scores.
8. CI, dependency/security scanning, monitoring, alerts and incident/rollback runbooks pass.
9. Backup/restore and disaster-recovery exercises have measured RPO/RTO and approved evidence.
10. A non-production three-plane end-to-end trace and negative security/regression tests pass.
11. Production deployment evidence exists for the exact release SHA/image/schema, with authorized human approval and post-deploy smoke tests.

A numeric score cannot override a failed mandatory gate. If any gate is not applicable, Agent 01 must state why and obtain architecture/security sign-off; it must not silently omit it.

## 6. Permissions and safety boundary

- Agent 01: GitHub App read-only permissions for the seven repos.
- Agents 02–09: GitHub App contents/issues/pull-requests write permissions only as required for task branches, commits, issue updates and PRs. Repository administration, ruleset management, Actions secrets, environment administration, bypass, merge and release permissions are denied.
- No shared PATs. Prefer one GitHub App installation restricted to the seven repos, with separate worker-side role enforcement and auditable agent identity.
- Worker credentials stay in a secret manager and are never sent to model context, prompts, artifacts or logs.
- Default branch writes, merging, releases, production deployment, production database mutations, secret rotation, external provider writes, bulk backfill and cutover require separate human approval.
- Disable dispatch writes until the worker's identity, GitHub App installation, branch protection and negative permission tests are verified.

## 7. Operational checkpoint and notification

Each hourly cycle records: UTC hour key, organization run ID, per-repo exact SHA, active task/owner, last completed step, blocker, next action, worker/dispatch status, and Agent 01 audit status. Retries must be idempotent across all seven repository schedules. A worker failure or missing credential is reported as BLOCKED, never as successful remediation.

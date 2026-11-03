# Institutional Production Gates

**Release decision: NO-GO until every mandatory gate has current, reproducible evidence.**

**Canonical specification:** [Master Engineering Specification](MASTER_ENGINEERING_SPECIFICATION.md). If a requirement or gate definition conflicts, the Master Engineering Specification is authoritative. This document is the compact release checklist and evidence procedure.

## 1. Release principles

1. A model, agent, worker, provider, planner, MCP server or connector is an execution component, not an authority.
2. Generated output, model cards, license statements, benchmarks and worker-reported metrics are untrusted until independently validated.
3. Every production action requires authenticated identity, explicit server-side authorization and a traceable correlation ID.
4. Production model revisions are immutable and pinned by source identity plus revision/digest.
5. Generation, workflow execution, model approval, artifact publication and release are separate state transitions.
6. Human approval is required for model promotion, policy exceptions, privileged external writes and production release.
7. Failed, incomplete, contradictory, stale or unavailable evidence remains BLOCKED, NOT RUN or NOT VERIFIED.
8. No release score or production claim overrides a failed mandatory gate.

## 2. Mandatory gates

| Gate | Required evidence |
|---|---|
| G0 — Scope and integrity | Primary and related repository boundaries fixed; candidate SHA frozen; protected branch and reviewed PR verified |
| G1 — CI and quality | Lint, unit, integration and migration tests green on the exact SHA |
| G2 — Identity and tenancy | Live authentication, least-privilege authorization, tenant/project adversarial tests and credential revocation |
| G3 — Secrets and audit | Secret scanning, key rotation/revocation, redaction and attributable privileged-action audit |
| G4 — Durable execution | Job state machine, idempotency, leases, restart recovery, retry and cancellation proven |
| G5 — Artifact trust | Scoped object access, immutable identifiers, checksum/MIME/parser validation and deletion proven |
| G6 — Model governance | Pinned model digest/license, independent evaluation, human promotion and rollback proven |
| G7 — RAG quality and safety | Frozen benchmark meets calibrated thresholds; provenance and abstention verified; cross-tenant leakage is zero |
| G8 — Agent/MCP controls | Sandbox, tool allowlist, authorization, OAuth, approval, audit and kill switch tested |
| G9 — Operations | SLO telemetry, numeric resource/cost budgets, alerts, runbooks, backup/restore and incident ownership |
| G10 — Supply chain | Dependency lock, SBOM, scans, provenance and immutable build artifact available |
| G11 — Resilience | Load/soak/failure-injection and disaster-recovery evidence meet approved objectives |
| G12 — Release control | Human approval binds exact code/config/model/migration artifacts; canary and rollback tested |

## 3. Evidence states

- **PASS:** current reproducible evidence exists for the exact candidate.
- **FAIL:** a required check ran and failed.
- **BLOCKED:** a prerequisite or capability is absent.
- **NOT RUN:** the check has not been executed.
- **NOT VERIFIED:** evidence exists but has not been independently validated.
- **NOT APPLICABLE:** justified with scope evidence and reviewer approval.

A release is NO-GO if any mandatory gate is FAIL, BLOCKED, NOT RUN or NOT VERIFIED. NOT APPLICABLE requires a documented, reviewed rationale.

Every evidence record must include requirement ID, repository, branch, full commit SHA, tool/version, environment, dataset/model/artifact digest where relevant, timestamp, result, retained report and reviewer where applicable.

## 4. Security baseline

- Production startup fails closed when identity, database, secret, policy or required model-governance configuration is missing.
- Development credentials and disabled authentication are never accepted in production.
- Secrets are supplied through a secret manager; real credentials are never committed.
- Tenant ID is derived from verified identity; caller-controlled tenant values are not authoritative.
- Every job, workflow, artifact, model operation, vector query and audit record is scoped and authorized server-side.
- Supabase grants and RLS policies are both reviewed; service-role/bypass-RLS credentials remain server-side and privileged operations enforce tenant scope explicitly.
- Worker-reported hardware and output metadata are claims, not attestations.
- Artifact access uses short-lived scoped authorization and byte-level verification.
- MCP tools use explicit registration, OAuth scopes and per-tool authorization; MCP connectivity is not proof of Git synchronization or autonomous execution.
- Rate limits, quotas, timeouts, concurrency/resource ceilings and cost budgets are enforced before expensive work starts.
- Destructive, external-write, deploy, publish, model promotion and policy-changing actions require the relevant approval gate.

## 5. Candidate verification procedure

1. Freeze the candidate repository, branch and full commit SHA.
2. Run the repository CI and migration tests against that exact SHA.
3. Run security and supply-chain scans; resolve critical/high findings or record a time-bounded, reviewed exception.
4. Deploy to production-like staging with live identity provider, isolated PostgreSQL, vector index and object storage.
5. Execute tenant isolation, access revocation, worker lease/restart, idempotency, artifact integrity and audit tests.
6. Execute real model/provider tests on the intended runtime; preserve model digest, hardware/runtime profile, inputs, outputs and QC results.
7. Run the frozen RAG and agent evaluation suites; preserve dataset version, denominators and confidence intervals.
8. Run load, failure-injection, backup/restore, canary and rollback tests.
9. Review the evidence pack and obtain human approval bound to exact artifact digests.
10. Deploy only the approved candidate; monitor SLO/error-budget gates and stop or roll back on breach.

## 6. Current baseline decision

**NO-GO / NOT PRODUCTION READY.**

This decision applies to the inspected `hardening/institutional-production-v1` engineering baseline as of 2026-11-03; it must be reevaluated against a later frozen candidate and fresh evidence. The repository has useful foundations: FastAPI, a PostgreSQL-backed external GPU queue, worker-specific credentials, model registry, OIDC integration contract and a Diffusers text-to-image adapter. These are not equivalent to a validated institutional production service.

Known blockers include complete tenant-aware IAM/RBAC, trusted artifact storage, fully executable durable pipeline orchestration, independent model/weight verification, validated real multimodal providers, complete agent sandbox, full observability and cost enforcement, supply-chain attestations, load/resilience tests, live provider/GPU smoke tests and human-controlled production deployment/rollback.

Do not change this decision based solely on documentation, interface presence, mock tests or green unit tests.

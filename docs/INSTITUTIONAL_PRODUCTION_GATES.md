# Institutional Production Gates

**Release decision: NO-GO until every mandatory gate has current, reproducible evidence.**

This document defines release controls. It is not a claim that controls are implemented or that the service is production-ready.

## 1. Institutional principles

1. A model, agent, worker, provider, or planner is an execution component, not an authority.
2. Generated output, model cards, license statements, benchmarks, and worker-reported metrics are untrusted until independently validated.
3. Every production action requires an authenticated actor or workload identity, explicit authorization, and a traceable correlation ID.
4. Production model revisions are immutable and pinned by repository identity plus immutable revision/digest.
5. Generation, pipeline execution, model approval, artifact publication, and release are separate state transitions.
6. Human approval is required for model approval, policy exceptions, and production release. Automation may prepare evidence but may not self-approve.
7. Failed, incomplete, contradictory, or unavailable evidence remains BLOCKED or NOT VERIFIED.

## 2. Mandatory release gates

| Gate | Required evidence | Current repository boundary |
|---|---|---|
| G0 Repository integrity | Protected release branch, reviewed PR, pinned dependencies | Repository-owner configuration required |
| G1 CI quality | Ruff, unit tests, PostgreSQL integration and migration tests green on exact commit | CI exists; fresh candidate run required |
| G2 Identity and tenancy | Live OIDC, tenant/project isolation, admin RBAC, worker identity and revocation | OIDC contract exists; live IdP, complete admin RBAC and external-job tenancy remain gaps |
| G3 Durable execution | API restart recovery, lease expiry, idempotency, cancellation, retry and dead-letter tests | External GPU queue is durable; general generation still has synchronous inference limitations |
| G4 Artifact trust | Object storage, immutable asset IDs, scoped signed access, checksum/MIME/parser validation | Not complete |
| G5 Model governance | Independent license review, immutable weight digest, reproducible evaluation, reviewer identity, disable/rollback test | Registry gate exists; evidence is operator-supplied and weight attestation is incomplete |
| G6 Pipeline execution | Executable typed DAG, stage persistence, dependency validation, retry/cancel and QC gates | Planner only; execution engine incomplete |
| G7 Real modality evidence | Real provider smoke tests on intended GPU/runtime | Image adapter exists; multimodal real-provider evidence absent |
| G8 Operations | Structured logs, metrics, traces, alerts, cost attribution and runbooks | Incomplete |
| G9 Supply chain | Lockfile, SBOM, dependency/image scanning, provenance and secret scanning | Incomplete |
| G10 Resilience | Load, failure injection, backup/restore and multi-replica evidence | Not verified |
| G11 Release control | Human approval bound to exact commit, model digests, migrations and deployment artifact; rollback evidence | Not implemented end-to-end |

## 3. Required state model

- PASS: automated or independently reviewed evidence exists for the exact candidate.
- FAIL: a required check ran and failed.
- BLOCKED: a prerequisite or capability is absent.
- NOT RUN: the check has not been executed.
- NOT VERIFIED: evidence exists but has not been independently validated.

A release is NO-GO if any mandatory gate is FAIL, BLOCKED, NOT RUN, or NOT VERIFIED.

## 4. Production security baseline

- Production startup must fail closed when authentication, database, worker credentials, or model-governance configuration is missing.
- No shared development token may be accepted in production.
- Secrets must be supplied through a secret manager; never commit secrets or real environment files.
- Every tenant-owned job, artifact, model operation, and audit event must be scoped and checked server-side.
- Worker-reported hardware and output metadata are claims, not attestations.
- Artifact downloads require short-lived scoped authorization and byte-level verification before publication.
- Privileged actions must be attributable to a human or workload identity and recorded in an append-only audit trail.
- Rate limits, quotas, resource ceilings, and cost budgets must be enforced before expensive work starts.

## 5. Candidate verification procedure

1. Freeze the candidate commit and record its SHA.
2. Run CI and migration tests against that SHA.
3. Run security scans and resolve critical/high findings or document an approved, time-bounded exception.
4. Deploy to production-like staging with a live OIDC provider and isolated PostgreSQL/object storage.
5. Execute tenant-isolation, worker-revocation, API-restart, lease-recovery, artifact-integrity, and rollback tests.
6. Execute real provider tests on the intended GPU platform. Preserve input, output, model digest, worker/runtime versions, logs, and QC results.
7. Run load and failure-injection tests; verify backup restoration.
8. Review the evidence pack and obtain human release approval.
9. Deploy the exact approved artifact and monitor rollout; stop or roll back on failed health/error-budget gates.

## 6. Current decision

**NO-GO / NOT PRODUCTION READY.**

The repository has useful foundations: FastAPI, PostgreSQL-backed external GPU queue, worker-specific credentials, model registry, OIDC integration contract, and a Diffusers text-to-image adapter. These are not equivalent to a validated institutional production service.

Release blockers remain: complete tenant-aware IAM, trusted artifact storage, executable durable pipeline orchestration, independent model/weight verification, real multimodal providers, observability, supply-chain controls, load/resilience tests, live GPU smoke tests, and human-controlled release/rollback.

Do not change this decision based solely on documentation, interface presence, mock tests, or green unit tests.

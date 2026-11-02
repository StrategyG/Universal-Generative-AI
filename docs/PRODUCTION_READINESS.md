# Production Readiness — Current Evidence-Based Decision

## Release decision: NO-GO / NOT PRODUCTION READY

This document supersedes earlier readiness language that described the repository
as production-ready. A successful unit-test workflow or the presence of a control
module is not equivalent to end-to-end production certification.

The current development line is the institutional hardening work and its follow-up
upgrade branches. Every release decision must be recalculated against one frozen
candidate commit; this document is a repository-level status baseline, not a
certification for an arbitrary future commit.

## Evidence-backed status

| Gate | Current state | Evidence / remaining boundary |
|---|---|---|
| Repository integrity | NOT VERIFIED | Branch protection and a reviewed, merged release candidate are not established |
| CI quality | PASS on previously checked head; new candidate pending | Ruff and PostgreSQL-backed pytest passed on commit 95064811c9e3936fe3647cabdf8d4c0f7bc4060e; rerun on every candidate |
| Identity and tenancy | PARTIAL | OIDC contract and generation scope exist; live IdP, complete admin RBAC, external-job tenant scope and artifact ACLs remain |
| Durable execution | PARTIAL | External GPU queue has persistence, leases and retries; general inference remains synchronous and workflow execution is not durable |
| Artifact trust | BLOCKED | Trusted object storage, signed access and server-side checksum/MIME/parser validation are incomplete |
| Model governance | PARTIAL | Immutable revision registry and approval gate exist; independent license, weight and evaluation verification remain |
| Workflow execution | BLOCKED | DAG planner persists plans but returns execution disabled / not configured |
| Real modality evidence | BLOCKED | Diffusers adapter exists; live GPU and multimodal pipeline smoke tests are not evidenced |
| Operations | BLOCKED | Structured metrics, traces, alerts, cost attribution and operational runbooks are incomplete |
| Supply chain | PARTIAL | Python dependency audit exists; SBOM, container scan, secret scan and signed build provenance are not complete |
| Resilience | NOT VERIFIED | Load, failure injection, backup/restore and multi-replica tests are not evidenced |
| Release control | BLOCKED | Human approval bound to exact commit/artifact and end-to-end rollback evidence are incomplete |

## Model-provider status

The repository has an OpenAI-compatible text generation adapter and a Diffusers
text-to-image adapter. The text endpoint has historically used a single configured
provider. Provider compatibility does not imply native support for all vendor
features. Native Anthropic and Gemini adapters, cross-model independent review,
tool execution, dynamic model discovery, cost-optimal routing and autonomous
multi-agent orchestration must not be represented as complete until implemented
and tested.

## Release policy

A release remains NO-GO while any mandatory gate is BLOCKED, FAIL, NOT RUN or
NOT VERIFIED. Do not merge or deploy based solely on documentation, interface
presence, mock responses, local tests or a green dependency scan.

A release candidate must include:
1. A frozen commit SHA and reproducible build manifest.
2. Green CI and ordered migration tests on that exact SHA.
3. Live OIDC and tenant-isolation evidence.
4. Durable executor, recovery, cancellation and idempotency evidence.
5. Artifact integrity and scoped access evidence.
6. Real provider/GPU smoke tests and model revision provenance.
7. Security, load, backup/restore and rollback evidence.
8. Human approval tied to the exact artifact digest and deployment target.

## Operational preconditions

Production must use a secret manager, verified authentication, PostgreSQL,
approved immutable model revisions, least-privilege service credentials and
explicit budget/resource limits. Development memory mode and mock providers are
not production configurations.

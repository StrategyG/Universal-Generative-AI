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
| CI quality | PASS on upgrade head 979bb90896d08775e5e657e64147e7502f27f695 | Ruff clean; 89 tests passed with 1 Starlette/httpx deprecation warning; rerun on every candidate |
| Identity and tenancy | PARTIAL | OIDC contract and generation scope exist; live IdP, complete admin RBAC, external-job tenant scope and artifact ACLs remain |
| Durable execution | PARTIAL | External GPU queue has persistence, leases and retries; general inference remains synchronous and workflow execution is not durable |
| Artifact trust | BLOCKED | Trusted object storage, signed access and server-side checksum/MIME/parser validation are incomplete |
| Model governance | PARTIAL | Immutable revision registry and approval gate exist; independent license, weight and evaluation verification remain |
| Workflow execution | BLOCKED | DAG planner persists plans but returns execution disabled / not configured |
| Real modality evidence | BLOCKED | Diffusers adapter exists; live GPU and multimodal pipeline smoke tests are not evidenced |
| Operations | PARTIAL | Request IDs and allow-listed JSON request logs exist; metrics, distributed traces, alerts, cost attribution and complete runbooks remain |
| Supply chain | PARTIAL | pip-audit reported no known vulnerabilities in audited installed dependencies; the local project package was not found on PyPI and therefore was not audited by pip-audit; SBOM, container scan, secret scan and signed build provenance remain incomplete |
| Resilience | NOT VERIFIED | Load, failure injection, backup/restore and multi-replica tests are not evidenced |
| Release control | BLOCKED | Human approval bound to exact commit/artifact and end-to-end rollback evidence are incomplete |

## Model-provider status

The repository has an OpenAI-compatible text generation adapter, native Anthropic
Messages API and Gemini generateContent adapters, plus a Diffusers text-to-image
adapter. The text router supports explicitly configured provider ordering,
primary/fallback routing, transient-error retries, streaming, model-catalog
discovery, normalized token usage, and production model-registry checks. Live
provider smoke tests with real user credentials are not yet evidenced. Unified
tool execution, structured outputs, cross-model independent evaluation,
cost-optimal model selection, automatic health scoring and autonomous
multi-agent orchestration remain incomplete.

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

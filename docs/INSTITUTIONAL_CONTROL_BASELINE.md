# Institutional Control Baseline

This is an engineering control baseline, not a certification, regulatory attestation, or proof of production deployment.

## Status vocabulary

- **PASS**: implemented and verified by identified automated or operational evidence.
- **PARTIAL**: a limited implementation exists; material controls remain incomplete.
- **BLOCKED**: a prerequisite or critical implementation is absent.
- **NOT RUN**: a test or procedure has not been executed.
- **NOT VERIFIED**: code or configuration exists, but there is no adequate operational evidence.

## Current control assessment (2026-10-31)

| Control domain | Status | Evidence and residual gap |
|---|---|---|
| API / provider separation | PARTIAL | FastAPI, provider registry, mock, optional Diffusers adapter; no real multimodal execution chain |
| External queue persistence | PARTIAL | PostgreSQL backend and SQL migration are committed; target database migration, restart and multi-worker behavior still require CI/live verification |
| Production queue fail-closed | PARTIAL | Startup rejects production mode without DATABASE_URL; operational deployment configuration is not verified |
| Worker authentication | PARTIAL | Shared token with constant-time comparison; no per-worker scopes, rotation, expiry or revocation |
| Worker capability registry | BLOCKED | No registration/discovery/scheduler implementation |
| User authentication / RBAC / tenant isolation | BLOCKED | No trusted user identity, tenant boundary, project ACL or asset authorization |
| Idempotency / cancellation | BLOCKED | No idempotency key, cancellation state or replay-safe completion |
| Artifact integrity | BLOCKED | No storage checksum verification, signed URL enforcement or server-side content inspection |
| Model provenance | PARTIAL | Model ID/revision may be recorded; registry, license verification and attestation absent |
| Audit trail | BLOCKED | No append-only actor/action log |
| Reliability | PARTIAL | PostgreSQL row locking, lease expiry and bounded retry implemented; no recovery exercise or transactional orchestration across pipeline stages |
| Observability | BLOCKED | No traces, metrics, alerting or cost attribution |
| Model quality evaluation | BLOCKED | No approved test corpus, benchmark, or calibrated release thresholds |
| Human oversight | PARTIAL | Current pipelines remain planning-only; there is no formal production approval workflow |
| Supply-chain security | BLOCKED | No SBOM, container/dependency scanning or model artifact allowlist gate |
| Multimodal providers | BLOCKED | PNG-to-GLB, rigging, motion, optimization and GLB-to-MP4 have no verified real provider execution |

## Trust boundaries

1. User-to-API: authenticate and authorize every request against tenant, project, and asset ownership.
2. API-to-database: validate job schema and persist job transitions transactionally.
3. API-to-worker: use worker-scoped credentials, lease tokens, capability constraints and short expiry.
4. Worker-to-storage: use short-lived scoped upload/download URLs; never accept a worker path as artifact proof.
5. Storage-to-pipeline: verify bytes, checksum, MIME, maximum size, parser/schema, and task-specific quality gates.
6. Model supply chain: pin immutable revisions and retain source, license, intended-use and evaluation evidence.
7. Operator-to-production: require human approval for releases, credential rotation, permission changes and destructive operations.

## Production exit criteria

Production approval requires a durable queue and tested recovery; identity and tenant isolation; scoped worker credentials; verified object storage and checksums; end-to-end PNG-to-GLB and GLB-to-MP4 on actual external GPU runtimes; security, load and quality gates; operational audit/monitoring/backups; and a human-approved release with rollback evidence.

**Current decision: NOT PRODUCTION READY.**

# Institutional Control Baseline

## Purpose and scope

This document defines minimum controls for operating Universal Generative AI as an institutional multimodal generation platform. It is an engineering baseline, not a certification, compliance attestation, or statement that controls are already deployed.

Status vocabulary:
- **PASS**: implemented and verified by an identified test or operational evidence.
- **PARTIAL**: a limited implementation exists, but coverage is incomplete.
- **BLOCKED**: a prerequisite or critical implementation is missing.
- **NOT VERIFIED**: no adequate test or operational evidence is available.

## Current control assessment

| Control domain | Current status | Evidence / gap |
|---|---|---|
| Architecture separation | PARTIAL | FastAPI control plane and provider abstraction exist; pipeline execution is not wired |
| Worker authentication | PARTIAL | Shared token and constant-time comparison; no worker-scoped identity, rotation, or revocation |
| Authorization / tenant isolation | BLOCKED | No end-user identity, tenant boundary, or per-asset authorization |
| Durable job state | BLOCKED | External queue is process-memory only; restart loses jobs |
| Artifact integrity | BLOCKED | No enforced checksum, signed upload/download URL, or server-side artifact inspection |
| Model provenance | PARTIAL | Model ID/revision metadata can be reported; not cryptographically attested or verified |
| Audit trail | BLOCKED | No append-only actor/action/event log |
| Reliability | PARTIAL | Leases and bounded retry exist; no durable scheduler, cancellation, dead-letter queue, or tested recovery |
| Observability | BLOCKED | No structured traces, metrics, alerting, or cost attribution |
| Model quality evaluation | BLOCKED | No approved evaluation dataset, benchmark report, or release gate |
| Human oversight | PARTIAL | Pipeline is currently planning-only; no approval workflow for high-impact execution |
| Supply-chain security | BLOCKED | No dependency/SBOM/image scanning or model artifact allowlist gate |

## Required trust boundaries

1. **Client to API**: authenticate users; authorize every operation against tenant and project scope; rate-limit requests.
2. **API to queue**: persist an immutable, versioned job envelope and an audit event in one transaction.
3. **Queue to notebook worker**: issue short-lived worker-scoped credentials; bind lease ownership to worker identity; reject replayed or stale lease tokens.
4. **Worker to asset storage**: use scoped, short-lived upload/download URLs; never give notebooks broad storage credentials.
5. **Artifact to pipeline**: verify checksum, file signature, size, schema, malware/content policy, and expected output type before downstream execution.
6. **Model supply chain**: pin immutable model revisions, record license and source, and permit only reviewed model identifiers.
7. **Operator to production**: require explicit approval for deployment, policy changes, credential rotation, and destructive operations.

## Versioned job envelope minimum

Every production job should include:
- schema_version, job_id, idempotency_key, trace_id
- tenant_id, project_id, requested_by, created_at
- task_type, input_asset_id, input_sha256
- model_id, immutable model_revision, model_license_ref
- resource_requirements including accelerator family and minimum VRAM
- attempt, deadline, priority, and cancellation state
- expected output MIME type, schema version, maximum size, and validation profile

The server must derive tenant and requester identity from authenticated credentials, never trust those fields when supplied by an untrusted notebook.

## Worker security requirements

- Replace the shared worker token with per-worker credentials, scopes, expiry, rotation, and revocation.
- Bind each lease to worker identity and a high-entropy lease token; compare lease token hashes server-side.
- Worker registration must report platform, runtime version, GPU model, VRAM, CUDA/runtime versions, supported task types, and capacity.
- A worker must not choose arbitrary model revisions or fetch arbitrary URLs.
- Heartbeats must be independent of long-running inference so notebook jobs do not expire while computing.
- Treat notebook runtimes as ephemeral and untrusted: no long-lived secrets, no broad storage credentials, and no trust in returned artifact paths alone.

## Reliability and data controls

- Use a durable queue backed by PostgreSQL or a managed queue; use transactional claiming and idempotent completion.
- Use a dead-letter state after bounded retries, preserving failure classification and trace context.
- Store artifacts in object storage with immutable object IDs, SHA-256 checksums, retention policy, encryption, and scoped signed URLs.
- Keep append-only audit events for job creation, claim, heartbeat, retry, completion, artifact validation, approval, and administrative changes.
- Define backup/restore objectives and prove recovery with scheduled exercises.

## AI governance and quality gates

Before enabling a model or pipeline in production:
1. Review model provenance, license, intended use, limitations, and known failure modes.
2. Define a task-specific evaluation dataset with held-out cases and representative edge cases.
3. Measure output validity, task success, consistency, latency, GPU memory, failure rate, and cost per accepted artifact.
4. Add safety and abuse tests appropriate to the modality and deployment context.
5. Set measurable release thresholds and a rollback procedure.
6. Require human review for uncertain, failed, policy-sensitive, or high-impact outputs.

Suggested release gate (to be calibrated per task, not assumed achieved):
- 100% schema/file-parse validity on the release test set.
- At least 95% successful completion on repeatable infrastructure tests.
- At least 90% task-specific human-rated acceptance on a representative pilot set.
- 100% traceability for model revision, input checksum, output checksum, and worker execution.
- No unresolved critical/high security findings.

## Production exit criteria

The platform must not be labelled production-ready until:
- durable queue and artifact storage are deployed and recovery-tested;
- user/tenant authentication and authorization are enforced;
- worker-scoped credentials and least-privilege asset access are verified;
- end-to-end PNG-to-GLB and GLB-to-MP4 workflows run on real Kaggle/Colab sessions;
- artifact validation and provenance checks reject malformed or tampered results;
- quality, load, security, and failure-injection tests meet documented gates;
- monitoring, alerting, audit retention, backup, and incident runbooks are operational;
- a human-approved release decision records the evidence and rollback plan.

## Current decision

**NOT PRODUCTION READY.** The repository has a useful architectural scaffold and a prototype external-worker protocol. It does not yet satisfy the institutional controls above. This document records the target baseline; it does not claim those controls have been implemented.

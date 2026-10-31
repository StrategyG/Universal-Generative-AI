# Architecture and implementation boundaries

## Control plane

- FastAPI API for health, basic generation requests, job inspection, and workflow planning.
- Provider registry with an explicitly simulated mock adapter and an optional Diffusers/SDXL adapter.
- External GPU queue facade selects PostgreSQL when `DATABASE_URL` is configured; otherwise it uses an in-memory development backend.
- Production startup rejects a missing `DATABASE_URL` rather than silently starting with volatile external-GPU job storage. When PostgreSQL is selected, startup also checks that `external_gpu_jobs` exists and fails if migration `0001` has not been applied.

## External GPU queue

The PostgreSQL backend is implemented in `app/services/postgres_gpu_queue.py`. Its migration is `migrations/0001_create_external_gpu_jobs.sql`.

Current queue behavior:
- Job creation persists platform, task, input reference, prompt, model ID/revision, options, idempotency key and request fingerprint, attempts, lease, result reference, metadata, and error.
- Claim uses a transaction and `SELECT ... FOR UPDATE SKIP LOCKED` to avoid two workers claiming the same available row.
- Expired leases are returned to the queued state until the retry limit; exhausted jobs move to `dead_letter`.
- Heartbeat, completion, and failure require matching worker ID and an unexpired lease.
- Job creation is durable across API restarts when PostgreSQL is configured and the migration has been applied.

Important scope boundaries:
- Only `/api/v1/external-gpu/*` uses this queue. General `/api/v1/generate` requests still use an in-memory job store.
- There is no idempotency key, transactional outbox, tenant scope, job cancellation, or worker-scoped credential system yet.
- The configured shared worker token remains a prototype control.
- The PostgreSQL backend is not production-verified until a target environment applies the migration and passes a recovery test.

## External worker execution

Kaggle and Google Colab are ephemeral outbound-polling workers. The control plane does not attempt to start, keep alive, or control a notebook session through unsupported platform APIs.

Expected flow:
1. An operator starts a notebook runtime and supplies API URL and credentials through notebook secrets.
2. The notebook polls the API and claims a compatible platform job.
3. A reviewed task handler downloads authorized input, runs a pinned model revision, uploads the artifact, and reports its asset reference and provenance.
4. The control plane verifies the artifact before allowing downstream pipeline stages.

Current worker client supplies outbound polling and a dedicated heartbeat thread during long handlers. It does not supply model handlers, storage integration, per-worker scoped credentials, or capability registration. Extended network outages can still outlast the lease.

## Pipeline contracts

The planner supports image-to-3D, image-to-video, and GLB-to-video plans. It returns stage dependencies, resource profiles, expected artifacts, and acceptance checks. Provider execution remains marked `unconfigured` / `not_implemented`. No plan response is evidence of model inference.

## Target execution boundaries

1. API validates and authorizes requests.
2. Durable orchestration assigns typed jobs to capability-matched workers.
3. Model adapters execute pinned, license-reviewed model revisions.
4. Artifact validation checks actual stored bytes, MIME, checksums, and format contracts.
5. Downstream stages run only after upstream output validation.
6. Blender/FFmpeg rendering converts validated scene/animation inputs to MP4.
7. Evaluation and audit evidence determine whether a model or pipeline revision can be released.

## Current production gaps

- Per-worker authentication, worker registration, revocation, capability matching, and lease tokens.
- Queue idempotency, cancellation, scheduling priority, and pipeline-stage persistence.
- Object storage, signed URLs, checksum enforcement, and actual artifact inspection.
- User authentication, RBAC, project permissions, and tenant isolation.
- Executable image-to-3D, GLB validation/optimization, rigging, motion, and rendering providers.
- Model registry/governance, quality evaluation, structured telemetry, audit events, SBOM and security scanning.

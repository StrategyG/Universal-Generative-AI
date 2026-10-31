# Universal Generative AI

A modular API and orchestration foundation for multimodal generative workflows.

## Implemented

- FastAPI generation API and job lookup.
- Provider registry with an explicit mock adapter and optional Diffusers/SDXL text-to-image adapter.
- Declarative pipeline planner for image-to-3D, image-to-video, and GLB-to-video workflows.
- Dependency-aware step plans with input-format validation, resource profiles, provider readiness, and acceptance checks.
- Docker packaging and GitHub Actions lint/test workflow.

## Run the API

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Health: `GET /health`

Submit a mock generation job: `POST /api/v1/generate`

```json
{"task":"text_to_image","prompt":"a cinematic red sports car"}
```

The default backend is `mock`. It simulates the provider contract and does not generate an image.

## Plan a multimodal workflow

`POST /api/v1/pipelines/plan`

```json
{
  "workflow": "image_to_video",
  "input_asset": "asset://uploads/character.png",
  "prompt": "A character waves at the camera"
}
```

The planner returns ordered steps, dependencies, resource profiles, expected artifacts, and acceptance checks. It is planning-only: it does not download assets, allocate GPUs, invoke models, or render video. All 3D, rigging, motion, and rendering workers remain unconfigured until implemented and validated.

Supported workflow names: `image_to_3d`, `image_to_video`, and `glb_to_video`.

## Enable real text-to-image inference

Install the optional runtime:

```bash
pip install -e ".[image]"
```

Set `GENERATION_BACKEND=diffusers-sdxl`, `GPU_REQUIRED=true`, `IMAGE_MODEL_ID`, and `IMAGE_MODEL_REVISION`. Pin the model revision to an immutable commit and verify the model license and hardware requirements before downloading weights. The first inference may download model weights and require substantial GPU VRAM.

## External GPU workers: Kaggle and Google Colab

The intended compute model is external GPU execution. The API/control plane does not require a local GPU for these worker tasks. Kaggle and Colab notebooks initiate outbound polling requests to the API; the API does not attempt to remotely control notebook runtimes.

Configure `WORKER_ADMIN_TOKEN` on the API host. In production, use the admin credential only from a trusted operator/orchestrator to provision and revoke workers or submit jobs. Provision a unique, short-lived worker token with `POST /api/v1/external-gpu/workers/provision` using the `X-Worker-Admin-Token` header and a body containing `worker_id`, `platform`, and `ttl_seconds`. The response contains the worker token once; store it in that notebook's secret store as `EXTERNAL_WORKER_TOKEN`. Also set `API_URL`, `WORKER_ID`, and an explicitly approved comma-separated `WORKER_SUPPORTED_TASKS`. The notebook registers detected runtime/GPU capabilities before polling. Never commit or print credentials. Install the optional client with `pip install -e ".[worker]"`.

Worker protocol:
- `POST /api/v1/external-gpu/jobs`: enqueue a task for a selected platform.
- `POST /api/v1/external-gpu/workers/provision`: operator issues a short-lived, worker-specific credential.
- `POST /api/v1/external-gpu/workers/register`: worker registers runtime, GPU/VRAM, CUDA, framework and task capabilities.
- `POST /api/v1/external-gpu/workers/heartbeat`: worker refreshes available RAM/VRAM telemetry.
- `DELETE /api/v1/external-gpu/workers/{worker_id}`: operator revokes a worker credential.
- `POST /api/v1/external-gpu/claim`: authenticated worker claims a task matched against its registered platform, supported tasks, VRAM, RAM and capacity.
- `POST /api/v1/external-gpu/jobs/{job_id}/heartbeat`: renew the 15-minute lease.
- `POST /api/v1/external-gpu/jobs/{job_id}/complete`: report an artifact reference and model metadata.
- `POST /api/v1/external-gpu/jobs/{job_id}/fail`: report failure; bounded retries use persisted exponential backoff (5 seconds initially, capped at 300 seconds; maximum three attempts).
- `POST /api/v1/external-gpu/jobs/{job_id}/cancel`: operator cancels a queued/running external-GPU job; late worker completion is rejected.
- `GET /api/v1/external-gpu/jobs/{job_id}`: inspect job state.

A worker must download only trusted, authorized input assets and upload outputs to approved object storage before reporting the resulting asset URI. The worker protocol does not implement model handlers, object storage, or notebook provisioning yet. Server-side cancellation invalidates the lease and rejects a late result; it does not forcibly stop a running GPU process inside Kaggle/Colab.

**Prototype limitation:** when `DATABASE_URL` is blank the external GPU queue falls back to in-process memory, which is development-only. Configure PostgreSQL and apply every ordered migration for durable jobs and worker credentials. `EXTERNAL_WORKER_TOKEN` is accepted only for development compatibility; production requires the provisioned, expiring, revocable per-worker token. Runtime capabilities are self-reported by an external notebook and are scheduling hints, not hardware attestation. Kaggle/Colab sessions remain ephemeral and subject to platform availability, quotas, idle shutdown, and runtime limits.

## Persistent external GPU queue

The external GPU queue supports a PostgreSQL backend for durable job state.

1. Install the optional dependency: `pip install -e ".[postgres]"`.
2. Set `DATABASE_URL` in the API environment (never commit a real credential).
3. Apply the initial migration: `for migration in migrations/*.sql; do\n  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$migration"\ndone`.
4. Start the API. The startup hook opens the PostgreSQL pool and verifies that `external_gpu_jobs` exists; startup fails with a migration-specific error when it does not. `GET /health` reports `queue_backend=postgresql` only after the queue has initialized.

When `DATABASE_URL` is empty, the external GPU queue uses in-memory development mode. That mode loses jobs on restart and is **not production-safe**.

Scope limitation: this PostgreSQL backend currently persists only `/api/v1/external-gpu/*` jobs. The general `/api/v1/generate` job store and pipeline planner are still in-memory/planning-only and are not yet connected to this durable queue. External-GPU idempotency, per-worker credentials and capability-based scheduling are implemented. Tenant-scoped user authorization and artifact verification remain outstanding.

## Not yet implemented

- Real PNG/JPG/WebP-to-GLB inference.
- GLB validation/optimization workers.
- Character rigging and motion-generation inference.
- Blender/FFmpeg rendering worker for GLB-to-MP4.
- General `/api/v1/generate` job history is now persisted in PostgreSQL, but inference remains synchronous in the request process; it is not yet a durable asynchronous generation queue. Object storage, user authentication, tenant isolation, quotas, and observability remain absent.
- Cooperative cancellation inside active notebook inference, executable pipeline orchestration, object storage/artifact validation, model governance, user/tenant auth, and end-to-end quality evaluation.

## General generation job persistence

When PostgreSQL is configured, `/api/v1/generate` writes its running and terminal job records to `generation_jobs`; `/api/v1/jobs/{job_id}` reads persisted history. This improves status durability but does **not** make inference asynchronous: the provider still runs inside the API request process. A process crash can leave a record in `running`; automated recovery/resumption is not implemented.

## Status

**Advanced prototype scaffold; not production-ready.** The repository does not contain newly trained foundation-model weights. The Diffusers adapter loads a configured pretrained checkpoint; the mock adapter is for tests only. Pipeline plans are contracts and resource estimates, not proof that a pipeline can execute.

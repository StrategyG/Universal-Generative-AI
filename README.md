# Universal Generative AI

A modular API and orchestration foundation for multimodal generative workflows.

## Implemented

- FastAPI generation API and job lookup.
- Provider registry with mock and Diffusers/SDXL image adapters.
- OpenAI-compatible text provider with bounded retry, explicit fallback routing, structured provider errors, and Server-Sent Events streaming.
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

## User authentication and tenant scope

Local development defaults to `AUTH_MODE=disabled` only when `ENVIRONMENT` is not `production`. In this mode, the API creates a local development principal; this mode is not suitable for any shared or public deployment.

Production startup fails closed unless `AUTH_MODE=oidc` and the following settings are provided:

- `OIDC_ISSUER`: exact token issuer.
- `OIDC_AUDIENCE`: API audience expected in the access token.
- `OIDC_JWKS_URL`: HTTPS JSON Web Key Set endpoint.
- `OIDC_TENANT_CLAIM`: tenant claim name (default `tenant_id`).
- `OIDC_ROLES_CLAIM`: role claim name (default `roles`).
- `OIDC_PROJECTS_CLAIM`: project membership claim name (default `project_ids`).

The current OIDC contract verifies RS256 signatures using the configured JWKS and requires `sub`, `iss`, `aud`, `exp`, and `iat`. The JWKS key set is cached for five minutes and network fetches use a five-second timeout; authentication fails closed when token verification cannot be completed. The token must contain a non-empty tenant claim. Supported platform role values are `developer`, `project_owner`, `tenant_admin`, `platform_admin`, and `read_only`. Generation requires a generation-capable role and a `project_id` included in the caller's project membership claim, except that a platform administrator may select a project within the tenant asserted by the token.

Generation history is stored with tenant, owner subject, and project scope. A caller can read a job only when it belongs to the same tenant and the caller is its owner, a member of its project, or a tenant administrator. Existing historical rows without ownership metadata remain inaccessible through the OIDC-scoped job API.

This is an identity-provider integration contract, not a built-in user database or login service. The identity provider remains responsible for user lifecycle, tenant membership, project membership freshness, MFA, and token issuance. Static worker/operator credentials remain a separate machine-identity path; full human RBAC for model-registry administration, rate limits, quotas, external-GPU job tenancy, and artifact authorization are not yet implemented.

Health: `GET /health`

Submit a mock generation job: `POST /api/v1/generate`

```json
{"task":"text_to_image","prompt":"a cinematic red sports car"}
```

The default backend is `mock`. It simulates the provider contract and does not generate an image.

## Institutional project workflow plans

The workflow control plane exposes deterministic starter plans for three project domains. These endpoints create plans only; they do not invoke an agent, modify a repository, generate media, call external tools, or deploy a project.

- `POST /api/v1/workflows/templates/coding` — requirements, architecture, code implementation, tests, security review, build, and deployment approval.
- `POST /api/v1/workflows/templates/film` — script, continuity review, storyboard, asset generation, shot assembly, rendering, quality review, and publication approval.
- `POST /api/v1/workflows/templates/workflow` — intake, classification, gated external action, reconciliation, and reporting.
- `POST /api/v1/workflows/plan` — validate and persist a caller-defined dependency graph.
- `GET /api/v1/workflows/plans/{plan_id}` — retrieve a saved plan within tenant/owner/project authorization scope.

Template request example:

```json
{
  "project_id": "project-123",
  "title": "Build a cooperative application",
  "objective": "Create a tested cooperative management application"
}
```

The server derives risk and side-effect classifications from its own action registry. Client-provided risk/side-effect hints cannot downgrade an action. Unknown actions fail closed as risk 5 and require human approval. Plans receive a stable `plan_id` and creation timestamp. With PostgreSQL configured they persist across API restarts in `workflow_plans`; development memory mode is volatile. Retrieval is tenant/owner/project scoped. Plans still return `execution_enabled=false` and `not_configured` stage statuses until durable step execution, sandboxing, artifact trust, and audit controls are implemented.

See [Institutional Workflow Control](docs/INSTITUTIONAL_WORKFLOW_CONTROL.md) and [Institutional Production Gates](docs/INSTITUTIONAL_PRODUCTION_GATES.md).

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

## Universal text model routing

The text generation API exposes two authenticated endpoints:

- POST /api/v1/ai/complete — single-shot or rigorous draft/critique/revision generation.
- POST /api/v1/ai/complete/stream — Server-Sent Events streaming; requires quality_mode=single.

The primary route uses TEXT_GENERATION_BASE_URL, TEXT_GENERATION_API_KEY and
TEXT_GENERATION_MODEL. An optional fallback route uses
TEXT_GENERATION_FALLBACK_BASE_URL, TEXT_GENERATION_FALLBACK_API_KEY and
TEXT_GENERATION_FALLBACK_MODEL. Configure the fallback URL and model together.
Production mode requires each configured route to have its own approved immutable
model ID and revision in the model registry.

The router retries only transient provider failures, applies bounded backoff,
and does not retry permanent errors such as invalid credentials or missing
models. Streaming can fall back only before the first token; after output begins,
the router never mixes partial generations from different models.

The authenticated GET /api/v1/ai/models endpoint probes each configured route's /models catalog and reports whether the configured model ID is listed. A provider may not implement model discovery; that route is reported as unavailable rather than being treated as proof of model absence.

The current adapter advertises streaming only. Tool calling, structured outputs,
vision, audio, video, native Anthropic/Gemini adapters, dynamic model discovery,
cost-optimal routing and cross-model independent evaluation are not implemented
by this text-provider release. See
[Universal Model Router](docs/UNIVERSAL_MODEL_ROUTER.md).

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

Scope limitation: the PostgreSQL backend persists both `/api/v1/external-gpu/*` jobs and `/api/v1/generate` job history. General generation inference remains synchronous in the request process and cannot be resumed after process termination. The pipeline planner remains planning-only. External-GPU idempotency, worker-scoped credentials and capability-based scheduling are implemented. Tenant-scoped user authorization and artifact verification remain outstanding.

## Not yet implemented

- Real PNG/JPG/WebP-to-GLB inference.
- GLB validation/optimization workers.
- Character rigging and motion-generation inference.
- Blender/FFmpeg rendering worker for GLB-to-MP4.
- General `/api/v1/generate` job history is now persisted in PostgreSQL, but inference remains synchronous in the request process; it is not yet a durable asynchronous generation queue. Object storage, user authentication, tenant isolation, quotas, and observability remain absent.
- Cooperative cancellation inside active notebook inference, executable pipeline orchestration, object storage/artifact validation, independent model-evidence verification, user/tenant auth, and end-to-end quality evaluation.

## Model registry and production approval gate

The PostgreSQL model registry stores immutable 40-character commit revisions. New revisions enter `pending_review`; production execution requires an `approved` record with license review, validation and evaluation evidence marked passed. Approval also requires an evaluation dataset version, timestamp and metrics record.

Admin-only registry routes use `X-Worker-Admin-Token`:
- `POST /api/v1/model-registry/versions` — register a model revision.
- `GET /api/v1/model-registry/versions?model_id=...&revision=...` — inspect it.
- `POST /api/v1/model-registry/versions/approve` — approve an evidence-complete pending revision.
- `POST /api/v1/model-registry/versions/disable` — disable a revision and cancel its queued/running external-GPU jobs.

The model approval gate applies to production external-GPU submissions and registered-worker scheduling. It also guards non-mock `/api/v1/generate` inference in production. Set `MODEL_REGISTRY_ENFORCEMENT=true` to exercise the gate in development; production enforces it regardless of this flag.

The registry stores evidence supplied by the operator. It does not independently determine legal license compatibility, rerun model validation, reproduce benchmark results, attest weights loaded by an external notebook, or provide reviewer identity/append-only approval audit. It is a control gate, not a certification or proof of model runtime integrity.

## General generation job persistence

When PostgreSQL is configured, `/api/v1/generate` writes its running and terminal job records to `generation_jobs`; `/api/v1/jobs/{job_id}` reads persisted history. This improves status durability but does **not** make inference asynchronous: the provider still runs inside the API request process. A process crash can leave a record in `running`; automated recovery/resumption is not implemented.

## Status

**Advanced prototype scaffold; not production-ready.** The repository does not contain newly trained foundation-model weights. The Diffusers adapter loads a configured pretrained checkpoint; the mock adapter is for tests only. Pipeline plans are contracts and resource estimates, not proof that a pipeline can execute.

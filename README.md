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

Configure `EXTERNAL_WORKER_TOKEN` on the API host and store the same value as a notebook secret/environment variable. Do not commit credentials or print them in notebook output. Install the optional worker client with `pip install -e ".[worker]"`.

Worker protocol:
- `POST /api/v1/external-gpu/jobs`: enqueue a task for a selected platform.
- `POST /api/v1/external-gpu/claim`: worker claims one matching task.
- `POST /api/v1/external-gpu/jobs/{job_id}/heartbeat`: renew the 15-minute lease.
- `POST /api/v1/external-gpu/jobs/{job_id}/complete`: report an artifact reference and model metadata.
- `POST /api/v1/external-gpu/jobs/{job_id}/fail`: report failure; retry up to three claims.
- `GET /api/v1/external-gpu/jobs/{job_id}`: inspect job state.

A worker must download only trusted, authorized input assets and upload outputs to approved object storage before reporting the resulting asset URI. The worker protocol does not implement model handlers, object storage, or notebook provisioning yet.

**Prototype limitation:** queue state and leases currently live in process memory. Restarting the API loses queued jobs; multiple API replicas do not share state. Replace this with a durable queue/database and per-worker credentials before production. Kaggle/Colab sessions are ephemeral and subject to platform availability, quotas, idle shutdown, and runtime limits; workers must tolerate interruption and resume from queued jobs.

## Not yet implemented

- Real PNG/JPG/WebP-to-GLB inference.
- GLB validation/optimization workers.
- Character rigging and motion-generation inference.
- Blender/FFmpeg rendering worker for GLB-to-MP4.
- Persistent queue, database, object storage, authentication, tenant isolation, quotas, and observability.
- GPU scheduling, retries, cancellation, and end-to-end quality evaluation.

## Status

**Advanced prototype scaffold; not production-ready.** The repository does not contain newly trained foundation-model weights. The Diffusers adapter loads a configured pretrained checkpoint; the mock adapter is for tests only. Pipeline plans are contracts and resource estimates, not proof that a pipeline can execute.

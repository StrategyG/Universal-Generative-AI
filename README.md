# Universal Generative AI

A modular platform and API for multimodal generative workflows.

## Implemented in v0.1 scaffold

- FastAPI generation API and job lookup.
- Provider registry with a deterministic mock adapter for contract tests.
- Optional local Diffusers/Stable Diffusion XL text-to-image inference adapter.
- Configurable model repository and immutable model revision.
- Artifact output to a local directory.
- Docker packaging and GitHub Actions lint/test workflow.

## Run the API

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Health: `GET /health`

Submit a mock job: `POST /api/v1/generate`

```json
{"task":"text_to_image","prompt":"a cinematic red sports car"}
```

The default backend is `mock`. It simulates the provider contract and does not generate an image.

## Enable real text-to-image inference

Install the optional runtime:

```bash
pip install -e ".[image]"
```

Set `GENERATION_BACKEND=diffusers-sdxl`, `GPU_REQUIRED=true`, `IMAGE_MODEL_ID`, and `IMAGE_MODEL_REVISION` in the environment. Use a model revision pinned to an immutable commit and verify the model license and hardware requirements before downloading weights. The first inference may download model weights and require substantial GPU VRAM.

## Roadmap — not yet implemented

- PNG/JPG/WebP to GLB using a separately provisioned 3D generation model.
- GLB validation, optimization, rigging, and motion generation.
- GLB to MP4 rendering using an isolated Blender/FFmpeg worker.
- Text/image to video.
- Persistent queues, object storage, authentication, tenant isolation, quotas, and observability.

## Status

**Prototype scaffold, not production-ready.** The repository does not contain newly trained foundation-model weights. The Diffusers adapter loads a configured pretrained checkpoint; the mock adapter is for tests only. 3D and video tasks currently have no real inference providers.

# Architecture and implementation boundary

## Current implementation
- FastAPI service with health, generation submission, and in-memory job lookup.
- Provider interface and registry with an explicitly simulated mock adapter.
- CI workflow for lint and unit tests.

## Target inference pipeline
1. Text/image input validation and asset ingestion.
2. Image-to-3D worker backed by a separately provisioned pretrained model (candidate families: TRELLIS.2 or Hunyuan3D).
3. GLB validation, optimization, and optional rigging/motion worker.
4. GLB-to-MP4 rendering worker using Blender in a GPU/CPU worker image, then FFmpeg encoding.
5. Artifact storage, provenance, job events, and retention controls.

## Important boundary
This repository does not contain trained foundation-model weights and does not currently execute real image, 3D, motion, or video inference. The mock provider exists only to test the API contract. Real providers must be implemented and evaluated independently, with pinned model revisions, licenses, checksums, GPU profiles, timeouts, and cost controls.

## Production gaps
- Persistent queue and database; current jobs are in process memory.
- AuthN/AuthZ, tenant isolation, quotas, rate limiting, and audit log.
- Object storage with signed URLs and malware/content validation.
- Real model adapters and worker isolation.
- Blender/FFmpeg worker image and sandboxing.
- GPU scheduling, cancellation, retries, observability, and evaluation datasets.
- Integration, load, security, and model-quality tests.

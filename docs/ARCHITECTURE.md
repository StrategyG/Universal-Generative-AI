# Architecture and implementation boundary

## Implemented control plane

- FastAPI service with health, generation submission, job lookup, and pipeline planning.
- Provider interface and registry; mock provider is explicitly simulated.
- Optional pinned-revision Diffusers/SDXL text-to-image adapter.
- Declarative workflow planner with dependency ordering, input extension checks, resource profiles, output contracts, and per-stage acceptance checks.
- CI workflow for lint and unit tests.

## Pipeline contracts

### Image to 3D
1. Image-to-3D inference: image -> GLB (GPU profile: 24 GB).
2. GLB validation: GLB -> validated GLB (CPU profile: 4 GB).

### Image to video
1. Image-to-3D inference.
2. GLB validation.
3. Character rigging and skin-weight validation.
4. Motion generation and animation-clip validation.
5. Rendering to MP4 and video decode validation.

### GLB to video
1. GLB validation.
2. GLB optimization with mesh-integrity checks.
3. Rendering to MP4 and video decode validation.

The planner emits dependencies, expected artifacts, resource profiles, and acceptance checks. The planner endpoint is planning-only. It does not execute a stage, download an input asset, allocate a GPU, or claim provider readiness. All steps are currently marked `not_implemented` and use provider `unconfigured`.

## Target worker architecture

1. API/control plane authenticates the caller and validates asset references.
2. Persistent queue dispatches immutable job envelopes to isolated workers.
3. Model workers load pinned model revisions and emit versioned artifacts.
4. Validation workers reject malformed or unsafe outputs before downstream stages.
5. Blender/FFmpeg render worker converts validated scene/animation artifacts to MP4.
6. Object storage retains artifacts with checksums, provenance, retention policy, and signed access.
7. Telemetry captures stage duration, GPU/VRAM, retries, cost, model revision, and quality metrics.

## Production gaps

- Persistent queue and database; current jobs are in process memory.
- AuthN/AuthZ, tenant isolation, quotas, rate limiting, and audit log.
- Object storage with signed URLs and malware/content validation.
- Real image-to-3D, rigging, motion, validation, optimization, and rendering workers.
- GPU scheduling, cancellation, retries, observability, and evaluation datasets.
- Integration, load, security, and model-quality tests.
- The current image adapter has not been verified with actual model weights or GPU inference.

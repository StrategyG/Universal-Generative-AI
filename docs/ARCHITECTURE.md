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

## External GPU execution model

Kaggle and Google Colab are external pull workers, not permanent GPU servers. The control plane enqueues a task tagged with its target platform. A notebook runtime polls the API over outbound HTTPS, claims a leased task, downloads the authorized input, executes a pinned model revision, uploads the output artifact, and reports completion with provenance metadata. The API does not assume it can start, stop, or keep a notebook session alive.

Current protocol routes are under `/api/v1/external-gpu`. They require the configured shared `EXTERNAL_WORKER_TOKEN`. A worker can only heartbeat or complete a job currently leased to its worker ID. Leases expire after 15 minutes and claims are retried at most three times.

The worker client is a transport helper only. Model-specific handlers must be supplied by a notebook runtime. The protocol is not yet connected to the multimodal pipeline planner or the existing generation endpoint.

### External worker lifecycle

1. User submits a generation request to the control plane.
2. Control plane persists an immutable job envelope and routes it to Kaggle or Colab.
3. Notebook worker polls and claims a lease.
4. Worker validates input, loads a pinned model revision, and performs inference.
5. Worker uploads output to object storage and reports its URI plus provenance metadata.
6. Control plane validates the artifact and advances the next dependent pipeline stage.

## Production gaps

- Persistent queue and database; current jobs are in process memory.
- AuthN/AuthZ, tenant isolation, quotas, rate limiting, and audit log.
- Object storage with signed URLs and malware/content validation.
- Real image-to-3D, rigging, motion, validation, optimization, and rendering workers.
- GPU scheduling, cancellation, retries, observability, and evaluation datasets.
- Integration, load, security, and model-quality tests.
- The current image adapter has not been verified with actual model weights or GPU inference.

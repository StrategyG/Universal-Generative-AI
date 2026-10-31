# Operations Runbooks

## Queue / database outage

1. Check API health and confirm `queue_backend` is `postgresql`.
2. Check PostgreSQL connectivity, pool errors, storage capacity and connection limits.
3. Do not switch production to memory mode; production startup intentionally requires `DATABASE_URL`.
4. Restore database availability from the approved recovery procedure.
5. Verify queued/running job counts and inspect expired leases before resuming workers.
6. Record incident timeline and failed job IDs.

## Worker disconnection / expired lease

1. Confirm the notebook runtime ended or lost network connectivity.
2. Wait for lease expiry; inspect attempts and error classification.
3. Allow bounded retry only when the task is safe to repeat.
4. After retry exhaustion, inspect the dead-letter record and operator decision before manual replay.
5. Do not mark an output successful based only on notebook output or a local file path.

## Model download failure

1. Verify model ID, immutable revision, source allowlist and license review.
2. Check runtime dependencies and available disk/memory.
3. Do not fall back to an arbitrary model revision.
4. Capture sanitized logs without access tokens or signed URLs.

## Invalid GLB / media output

1. Quarantine the asset; do not schedule downstream stages.
2. Preserve input/output checksums and model/runtime provenance.
3. Run parser/schema, mesh, material, texture and size checks in an isolated worker.
4. Classify the failure and retain the evidence for model evaluation.

## GPU out-of-memory

1. Record GPU model, VRAM, CUDA/framework revision and memory telemetry.
2. Do not silently lower output quality or change model revision.
3. Retry only with an approved resource profile or smaller user-approved output configuration.
4. Update resource requirements after repeatable measurements.

## Rendering failure

1. Verify Blender/FFmpeg version and GLB import.
2. Confirm frame range, frame rate, camera and lighting configuration.
3. Check temporary disk and output file size.
4. Validate MP4 by decoding it before marking the stage successful.

## Backup / restore

A database backup and restore procedure, retention period, RPO and RTO are not yet configured in this repository. Before production, define ownership and targets, automate encrypted backups, and run a scheduled restore exercise. Mark this runbook BLOCKED until evidence exists.

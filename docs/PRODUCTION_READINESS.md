# Production Readiness Assessment

**Decision: NOT PRODUCTION READY.**  
**Snapshot commit:** `2e1bffb3da5388f9ccea32efa0f55cb027fd1ebc`  
This is an engineering assessment, not a certification or assurance statement.

## Acceptance matrix

| Criterion | Status | Evidence / remaining gap |
|---|---|---|
| API health and basic endpoints | PARTIAL | FastAPI endpoint tests pass; no production hosting or load evidence |
| Ruff lint and unit tests | PASS | CI #62: Ruff PASS and 35 pytest tests passed |
| PostgreSQL external-GPU job persistence | PASS (CI scope) | PostgreSQL-backed queue, ordered migrations and restart/recovery integration tests run in CI; target database recovery remains unverified |
| General generation-job persistence | BLOCKED | `/api/v1/generate` still uses an in-memory job store |
| External-GPU idempotent submission | PASS (CI scope) | Same key/same request returns existing job; same key/different payload returns conflict |
| Worker-specific credentials | PASS (CI scope) | Random token issued to a provisioned worker; DB stores SHA-256 hash; expiry and revocation enforced |
| Worker rotation | PARTIAL | Re-provisioning changes token and clears old runtime registration; operational rotation procedure and incident exercise not run |
| Cryptographic lease-token binding | BLOCKED | Job lease is bound to worker ID and expiry, not to a separate signed/high-entropy lease token |
| Worker capability registration | PASS (CI scope) | Runtime/GPU/CUDA/framework/task/VRAM/RAM/capacity metadata is validated and stored |
| Capability-aware scheduling | PASS (CI scope) | Task/platform and memory requirements are matched; reported hardware details are not attested |
| Worker telemetry refresh | PASS (CI scope) | Client refreshes free VRAM/RAM before claim and while work is active; no live notebook evidence |
| Lease recovery / bounded retries | PARTIAL | Expired leases are reclaimed and attempts are bounded; cancellation, retry backoff and production chaos tests remain |
| Artifact checksum/content verification | BLOCKED | No trusted storage integration or server-side SHA-256/MIME/parser validation of actual object bytes |
| Executable pipeline dependency engine | BLOCKED | Planner only; no durable stage graph or stage-level execution/validation gates |
| Model registry and license gate | BLOCKED | Immutable revision metadata exists, but no approved-model registry or license review enforcement |
| User authentication, RBAC and tenant isolation | BLOCKED | Not implemented |
| Audit, tracing, metrics and cost attribution | BLOCKED | Not implemented |
| SBOM / dependency / container scanning | BLOCKED | Not implemented |
| Real Kaggle or Colab GPU smoke test | NOT RUN | CI does not start or control external notebook sessions |
| PNG-to-GLB real inference | NOT RUN | No configured provider and no accepted output evidence |
| GLB-to-MP4 real rendering | NOT RUN | No Blender/FFmpeg worker and no decoded video evidence |
| Human release approval and rollback | BLOCKED | No release approval workflow or tested rollback mechanism |

## Readiness score

These are engineering estimates, not externally audited ratings:

- **Engineering platform readiness: 4.1/10.** The control plane, durable external-GPU queue, worker credential registry, capability scheduling and CI integration are meaningful foundations. Most artifact, execution, governance and operations layers remain absent.
- **Institutional production readiness: 3.0/10.** Tenant security, artifact trust, audited operations, model governance, release controls and live multimodal evidence are still missing.

## Remaining production blockers

1. Persist general generation jobs and pipeline-stage state, not only external-GPU queue records.
2. Add tenant-aware user authentication, project permissions, rate limits and quotas.
3. Add cryptographic lease tokens, admin identity/access policy and stronger worker lifecycle controls.
4. Add object storage with scoped signed URLs, immutable asset IDs and server-side checksum/MIME/parser validation.
5. Implement executable pipeline orchestration with typed contracts, dependencies, cancellation, retry backoff and stage-level quality gates.
6. Implement reviewed model registry entries with immutable revisions, source/license review and rollback.
7. Implement real image-to-3D, GLB validation/optimization, rigging, motion and Blender/FFmpeg render providers.
8. Test real Kaggle/Colab execution, PNG-to-GLB and GLB-to-MP4 with preserved input/output provenance.
9. Add audit events, structured logs, metrics, traces, alerts, cost attribution, SBOM and vulnerability scanning.
10. Run production DB backup/restore, multi-replica, load, failure-injection and security tests.

## Minimum release gate

A release candidate must demonstrate repeatable API/PostgreSQL integration; persistence after an actual API process restart; worker token revocation and capability scheduling; tenant isolation; stored-byte integrity validation; successful real Kaggle or Colab PNG-to-GLB inference; decoded GLB-to-MP4 output; quality/security/load gates; operational monitoring and backup/restore; and a human approval record tied to the exact commit and model revisions.

Do not mark any blocked or unrun criterion PASS based on architecture or code presence.

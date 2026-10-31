# Production Readiness Assessment

**Decision: NOT PRODUCTION READY.** This is a point-in-time engineering assessment, not certification.

## Acceptance matrix

| Criterion | Status | Evidence required / remaining gap |
|---|---|---|
| API starts | PARTIAL | Base FastAPI app exists; production startup path not yet verified against deployed PostgreSQL |
| Existing and new tests | NOT VERIFIED | Latest branch CI must complete; test result cannot be inferred from earlier runs |
| Ruff lint | NOT VERIFIED | Earlier failures are fixed in later commits; run on current head required |
| PostgreSQL durable external queue | IMPLEMENTED / NOT VERIFIED | Backend and migration exist; verify current CI integration and independent restart/recovery in target environment |
| General generation job persistence | BLOCKED | `/api/v1/generate` still uses in-memory storage |
| External-GPU duplicate submission idempotency | PARTIAL | Idempotency key with payload fingerprint and conflict rejection; general generation jobs remain non-idempotent |
| Worker authentication/revocation | BLOCKED | Shared token only; no per-worker credentials or revocation |
| Capability registration/scheduling | BLOCKED | Platform-only routing; no GPU/VRAM/runtime capability registry |
| Lease recovery | PARTIAL | Lease expiry and bounded retry exist; multi-worker integration and operational recovery test required |
| Artifact checksum and content verification | BLOCKED | No enforced SHA-256 or parser validation of stored bytes |
| Pipeline dependency execution | BLOCKED | Planner only; no execution engine |
| Model registry/provenance gate | BLOCKED | Model revision metadata exists; allowlist/license gate absent |
| User auth / RBAC / tenant isolation | BLOCKED | Not implemented |
| Audit, logs, tracing, metrics | BLOCKED | Not implemented |
| Security scanning / SBOM | BLOCKED | Not implemented |
| Kaggle / Colab GPU smoke tests | NOT RUN | No live runtime credentials/session supplied |
| PNG-to-GLB real inference | NOT RUN | No configured real provider or output evidence |
| GLB-to-MP4 real rendering | NOT RUN | No Blender/FFmpeg worker or output evidence |
| Human release approval / rollback | BLOCKED | Governance process not wired into platform |

## Minimum release gate

A release candidate must demonstrate:
- repeatable API + PostgreSQL integration tests;
- queue persistence after API process restart;
- idempotent submission and completion;
- per-worker credentials and capability-based job selection;
- tenant isolation and artifact authorization;
- stored-byte checksum/MIME/parser validation;
- real Kaggle or Colab image-to-GLB output with provenance;
- real GLB-to-MP4 decode validation;
- failure injection, load, security and quality evaluation;
- monitoring, alerting, backup/restore and rollback exercises;
- human approval recorded against the exact version/revision.

No score or PASS designation should be granted without an evidence artifact and test/run identifier.

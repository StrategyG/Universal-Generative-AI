# UGAI V3.0 — P0 Execution Plan and Acceptance Gates

**Priority:** Reasoning first, with RAG and cross-plane controls as mandatory P0 dependencies.  
**Execution policy:** additive, reversible, evidence-gated.  
**Database policy:** Supabase remains active and authoritative; PostgreSQL VM is a DR/replication target until cutover acceptance; Google Drive is encrypted backup/archive. No dual business writers.

## 1. P0 exit objective

Deliver one auditable vertical slice:

`User request → UGAI evidence retrieval → reasoning/evaluation → policy decision → human approval (if required) → IM19 tool execution or Studio job → independent verification → durable audit record`

The slice is accepted only when the same tenant, actor, task ID, correlation ID, approval digest, and result evidence can be traced across every participating plane.

A mocked adapter may be used for unit tests, but acceptance requires at least one non-production integration environment with real authenticated service-to-service calls. Do not use production secrets in CI.

## 2. Workstreams and gates

### P0-A — Release baseline and repository governance

**Tasks**
- Choose and publish a release manifest for exact UGAI, IM19, and Studio SHAs.
- Resolve stacked PR dependencies in dependency order; do not merge a child before its base.
- Establish compatibility versions for decision envelope, task/event schemas, MCP tool schemas, and Studio job contracts.
- Pin runtime dependencies and image digests; remove placeholder digests.
- Require CI, security checks, license checks, migration checks, and owner review before merge.

**Acceptance**
- All three repositories have a named release-candidate SHA.
- No unresolved merge conflicts or unknown base dependency.
- CI green on the exact candidate SHAs.
- API/contract compatibility tests pass across all three repos.
- Release manifest can reproduce the tested build.

### P0-B — Institutional RAG publication gate

**Tasks**
1. Approve one embedding model artifact with immutable version, provider, dimensions, artifact/config digest, license, and evaluator record.
2. Verify source-document provenance, content hash, tenant, classification, retention, source version, and access scope.
3. Generate a small controlled staging batch first (minimum 30 chunks), not a bulk backfill.
4. Verify embedding dimensions, non-null coverage, deterministic retry behavior, duplicate suppression, and source-to-chunk lineage.
5. Activate at least two independently verified human reviewers under the configured reviewer policy.
6. Create and approve evidence excerpts with source/page/offset provenance.
7. Build an independently human-curated evaluation set meeting the database gate (minimum 50 qualifying cases), including answerable, unanswerable, false-premise, conflict, temporal, and access-control cases.
8. Run retrieval and citation evaluation; publish results and release evidence only after thresholds pass.

**Acceptance**
- Database readiness view reports 9/9 technical gates and 4/4 operational gates.
- No unauthorized tenant can retrieve another tenant's source or chunk.
- Every published claim has resolvable source provenance and citation span.
- Evaluation includes recall@k, precision@k, MRR/nDCG where applicable, citation precision/coverage, unsupported-claim rate, abstention accuracy, and access-control negative tests.
- Re-run the release view immediately before promoting the RAG release.

**Safety**
- Do not weaken release views or insert synthetic reviewer/evaluation records to make gates pass.
- Do not mark candidates published without actual human review and provenance validation.
- Do not run bulk embedding until the 30-chunk staging batch passes.

### P0-C — Reasoning runtime and evaluator

**Tasks**
- Connect the reasoning selector to the actual model registry/provider router.
- Enforce provider and model-family independence for high/critical risk evaluator routes.
- Persist decision envelopes, evidence references, assumptions, counterarguments, evaluator findings, confidence/uncertainty metadata, model/version trace, and verification outcome.
- Never persist private chain-of-thought. Store concise rationale, evidence, decision metadata, and audit events only.
- Add abstention, false-premise detection, temporal validity, contradiction handling, and evaluator disagreement resolution.
- Calibrate decision/evidence scores against labeled outcomes; never label heuristic indices as probabilities.

**Acceptance**
- Provider smoke tests pass for each enabled adapter in a non-production environment.
- Evaluator is independently routed and cannot approve its own originating model output.
- Frozen benchmark has at least 200 cases for release candidate evaluation, including adversarial and high-risk scenarios.
- Report factual accuracy, evidence/citation precision and coverage, unsupported-claim rate, abstention accuracy, false-premise detection, decision consistency, calibration, latency, and cost.
- High/critical-risk actions cannot proceed without policy approval.

### P0-D — Three-plane vertical slice

**Tasks**
- Establish service identity and tenant context propagation.
- Define versioned contracts for DecisionProposal, Approval, Task, ToolInvocation, StudioJob, Evidence, and ExecutionResult.
- Make policy authorization independent of model-generated tool proposals.
- Bind approval to actor, tenant, operation, target, exact payload digest, risk, and expiry.
- Execute IM19 calls with capability allowlists, bounded timeout, output validation, and credential isolation.
- Submit Studio jobs with bounded resources and artifact provenance.
- Record one correlation ID and immutable/append-oriented audit trail across services.

**Acceptance**
- One complete successful E2E workflow in non-production.
- Negative tests prove cross-tenant access is denied.
- Expired approval, altered payload, unauthorized tool, invalid output, and missing identity are rejected.
- All tool/job outcomes have independent verification evidence.
- No direct model-to-tool execution path bypasses policy.

### P0-E — Durable workflow and recovery

**Tasks**
- Integrate PostgreSQL-backed task store, lease/fencing, state machine, retries, cancellation, deadlines, and outbox into the actual service runtime.
- Require idempotency keys for all external side effects.
- Treat unknown external outcomes as reconciliation-required, not retryable by default.
- Use transactional outbox and idempotent consumers; document at-least-once delivery.
- Add dead-letter/blocked handling and operator recovery workflow.

**Acceptance**
- Crash tests at every state boundary.
- Duplicate message and duplicate request tests.
- Lease expiry/fencing tests with two workers.
- Provider outage, DB outage, timeout, expired approval, and malformed tool result tests.
- Recovery never repeats an uncertain non-idempotent side effect before reconciliation.

### P0-F — Security and operational baseline

**Tasks**
- Threat-model prompt injection, tool abuse, SSRF, credential exfiltration, tenant escape, unsafe code execution, replay, supply-chain compromise, and audit tampering.
- Verify runtime DB role, table ownership, RLS, grants, SECURITY DEFINER functions, secret scope and rotation.
- Add secret redaction, structured logs, metrics, traces, alerting, SLOs and incident runbooks.
- Fix AI Notebook Studio bundled UI asset CI failure before selecting its release SHA.
- Run dependency, container, SAST, DAST/API authorization and license checks.

**Acceptance**
- Security test suite passes on exact release SHAs.
- No critical/high unresolved findings without documented risk acceptance.
- SLO and alert thresholds have owners and tested notification paths.
- Incident response, rollback and credential rotation drills completed.

## 3. Hybrid data and DR policy

**Current decision**
- Supabase remains the authoritative system of record and single business writer.
- PostgreSQL VM is a replication/DR target; no promotion until lag, reconciliation, integrity, and failover/failback tests pass.
- Google Drive stores encrypted, versioned backup/archive objects, never live queue or database writes.

**Required controls**
- Define ownership per table/domain and a single-writer rule.
- Use an outbox for integration events; do not confuse event delivery with physical replication.
- Consumers must be idempotent; delivery semantics are at-least-once.
- Record source LSN/position or equivalent replication watermark, event ID, schema version, content digest, and reconciliation status.
- Monitor replication lag, missing/duplicate events, checksum mismatches, backup age, restore success, and storage capacity.
- Define explicit promotion fencing to prevent split-brain.
- Prove clean restore to an isolated target before any failover exercise.
- Measure and approve RPO/RTO; do not invent them.

**Cutover remains prohibited until**
- VM is provisioned and hardened;
- initial snapshot and continuous sync are verified;
- reconciliation reports zero unexplained divergence;
- encrypted Drive backup is independently restorable;
- failover and failback are rehearsed;
- application connection routing and rollback are tested;
- owner signs the cutover decision.

## 4. Delivery order and dependency graph

1. P0-A release baseline and contracts.
2. P0-B RAG staging model approval and provenance.
3. P0-C reasoning runtime and evaluator.
4. P0-D three-plane vertical slice.
5. P0-E durable recovery tests.
6. P0-F security and operations.
7. P0 hybrid DR acceptance in parallel, without cutover.

P0-B and P0-C can progress in parallel after contracts are frozen. P0-D depends on identity and contracts. P0-E must be integrated before the vertical slice is accepted. P0-F is continuous and gates every release.

## 5. Change-control boundaries

This plan authorizes additive repository documentation and non-production implementation work only. It does not authorize:
- production database DDL/DML or policy changes;
- secret creation, rotation, or disclosure;
- bulk embedding/backfill;
- production deployment;
- database cutover/failover;
- merging Draft PRs or changing protected release branches;
- granting autonomous financial, political, legal, or other high-impact authority.

Each action requires its own scoped authorization and evidence record.

## 6. Definition of done

P0 is complete only when every acceptance item has:
- exact repository SHA or environment identifier;
- reproducible test/evaluation result;
- named owner and reviewer;
- evidence link or retained artifact;
- explicit pass/fail status;
- rollback/recovery evidence where relevant.

A green CI badge alone is not production acceptance.

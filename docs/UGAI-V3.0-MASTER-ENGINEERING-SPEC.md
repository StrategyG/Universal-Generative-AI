# UGAI V3.0 — Master Engineering Specification

**Status:** Approved target architecture; implementation and production acceptance are NOT VERIFIED.  
**Priority:** Reasoning and Decision Intelligence.  
**Scope:** Full platform (15 subsystems), delivered through gated phases.  
**Architecture:** Three planes with hybrid infrastructure.

## 1. Executive decision

UGAI V3.0 is an Autonomous Institutional Intelligence System, not a chatbot plus unrestricted agents. It must observe evidence, reason, plan, request authorization where required, execute bounded actions, verify external effects, preserve provenance, and learn only through independently evaluated candidates.

The model is probabilistic. The orchestrator, policy enforcement, state transitions, persistence, authorization, and release gates are deterministic software controls.

## 2. System planes

### Plane 1 — UGAI Core Intelligence
Owns reasoning orchestration, model selection, memory policy, task planning, decision records, agent coordination, and workflow state.

### Plane 2 — IM19 MCP Execution
Owns MCP server/client integration, tool discovery, capability metadata, per-call authorization integration, credential isolation, bounded execution, and external-system adapters. MCP connectivity is not proof that an external operation succeeded.

### Plane 3 — AI Notebook Studio
Owns research/experimentation workspace, dataset preparation, knowledge-mining workflows, evaluation experiments, model candidate analysis, and human-reviewed learning/promotion workflows.

### Shared infrastructure
- PostgreSQL VM: target operational database for UGAI workflow/task state, leases, checkpoints, outbox, audit/evidence metadata, registry metadata, and application-owned records.
- Supabase: existing active Auth/RLS/RAG platform; retain during transition. Existing RAG remains canonical until a domain-specific migration and cutover are verified.
- Google Drive: encrypted backup/archive destination, not a live database or queue.
- Model runtime: self-hosted open-weight inference as the independence target; external model APIs remain optional adapters.
- Object storage: binary artifacts, datasets, model files and backup objects; metadata and content digests in the owning database.
- Queue: PostgreSQL-backed durable queue initially; add Redis or a broker only when measured throughput/latency requires it.

## 3. Fifteen subsystems

1. Unified Reasoning Engine — multi-step decomposition, evidence-grounded synthesis, hypothesis testing, uncertainty handling, counterarguments, and method selection.
2. Hybrid Model Runtime — version-pinned local/open-weight and optional hosted inference adapters.
3. Model Router — route by task capability, quality evidence, context, latency, cost, privacy and availability.
4. Decision Intelligence — alternatives, constraints, expected outcomes, risk, scenario and sensitivity analysis; decision records must preserve assumptions and evidence.
5. Memory Intelligence — scoped episodic, semantic, procedural and task memory with provenance, retention and deletion controls.
6. Autonomous Workflow Engine — durable DAG/task orchestration, state machine, leases, retries, deadlines, cancellation, idempotency and recovery.
7. Multi-Agent Orchestrator — capability-scoped agents, bounded delegation, cycle/depth limits and independent review.
8. Tool Execution Engine — allowlisted tool invocation, typed schemas, policy checks, timeouts, resource limits and output validation.
9. Verification & Recovery Engine — verify external effects against the owning system, reconcile interrupted work, rollback where supported, and report unverifiable outcomes.
10. Institutional RAG — ingestion, chunking, embedding, lexical/vector/hybrid retrieval, reranking, citations, versioning and tenant-aware access.
11. Knowledge Graph — entity/relation provenance, temporal validity, confidence, contradiction and lifecycle states.
12. Knowledge Mining — source-grounded pattern discovery, synthesis candidates, duplicate detection and contradiction detection.
13. Adaptive Learning — curate approved data, create candidate prompts/adapters/models, run reproducible experiments; never self-promote.
14. Evaluation & Benchmark — versioned datasets, baselines, independent evaluation, confidence intervals, regression and adversarial suites.
15. Governance & Security — identity, authorization, tenant isolation, secrets, approvals, immutable/append-oriented audit, policy, retention and incident controls.

## 4. Reasoning and decision contract

Every model decision must be treated as a proposal, not authority. Structured decision envelope:

- decision_id, task_id, correlation_id, actor/model/version
- objective and decision type
- evidence references and source versions
- assumptions and unknowns
- proposed action/tool and typed arguments (when applicable)
- risk class, required capabilities and approval requirement
- expected evidence and acceptance criteria
- expiry/deadline and idempotency key

Required reasoning discipline:
- distinguish observed facts, inference, assumptions and unknowns;
- cite source/evidence identifiers for material claims;
- compare at least one viable alternative for consequential decisions;
- use counterargument/adversarial review for high-impact decisions;
- do not invent repository paths, API contracts, metrics or execution outcomes;
- abstain or ask one targeted clarification when evidence is insufficient.

## 5. Workflow state machine

Canonical task states:
RECEIVED -> OBSERVING -> PLANNING -> AUTHORIZED -> READY -> RUNNING -> VERIFYING -> SUCCEEDED

Additional states: WAITING, AWAITING_APPROVAL, RETRY_WAIT, BLOCKED, FAILED, CANCELLED, EXPIRED.

Rules:
- state transitions are enforced by code and persisted transactionally;
- every task has tenant/project scope, owner, correlation ID, version, deadline, retry budget and idempotency key;
- lease acquisition/renewal uses compare-and-set/fencing tokens;
- retries are bounded and classified; non-idempotent side effects require reconciliation before retry;
- approval binds to exact actor, tenant, target, operation, payload/diff digest, risk and expiry;
- approval cannot be reused for a changed payload or future unrelated action;
- completion requires independent verification evidence.

## 6. Data ownership and hybrid migration

Single-writer ownership is mandatory per data domain. No unconstrained bidirectional replication.

| Domain | Current owner / transition | Target owner |
|---|---|---|
| Authentication and identity | Supabase Auth remains active | Supabase Auth unless a separately approved identity migration |
| Existing institutional RAG | Supabase project institutional-rag remains canonical until verified cutover | PostgreSQL VM after reconciliation and acceptance |
| Workflow, jobs, leases, checkpoints | UGAI-owned PostgreSQL VM when provisioned | PostgreSQL VM |
| IM19 credential vault | IM19's own PostgreSQL-backed encrypted vault | Remains IM19-owned; do not copy provider secrets into UGAI |
| Notebook documents and experiments | AI Notebook Studio application store (must be verified) | Explicitly assigned application database |
| Artifacts and model binaries | Object store / versioned artifact storage | Object store with digest and owner metadata |
| Backup archives | Google Drive | Google Drive plus tested independent recovery path |

Migration protocol:
1. inventory schema, row counts, extensions, grants, RLS, functions, indexes, jobs and data dependencies;
2. snapshot and verify backup;
3. define canonical IDs, source hashes, tenant mapping and migration manifest;
4. initial copy to target with checksums and row-level reconciliation;
5. controlled incremental sync using outbox/CDC with checkpoints and dead-letter handling;
6. compare counts, hashes, retrieval outputs and authorization behavior;
7. run shadow reads and tenant-isolation tests;
8. freeze writes only for a bounded cutover window, apply final delta, switch one domain at a time;
9. monitor and retain rollback path;
10. retire old writer only after signed acceptance and successful restore drill.

Never use Google Drive as a transactional synchronization layer. Backup success is not restore success.

## 7. Security baseline (P0/P1)

- verified identity, tenant/project membership and object-level authorization on every request;
- RLS as defense in depth; test privileged/service-role paths separately;
- deny-by-default tool registry and capability intersection across principal, project, task, agent and tool;
- secret manager; no secrets in prompts, client bundles, logs, artifacts or repository;
- sandboxed untrusted code with resource ceilings and default-deny network egress;
- prompt injection treated as untrusted data, never policy;
- action-bound approval for destructive, external write, deployment, merge, schema migration and secret operations;
- kill switch, cancellation, audit correlation, rate and cost budgets;
- pinned dependencies, lockfiles, SBOM, vulnerability scanning and signed release artifacts;
- backup encryption, key custody, retention, RPO/RTO and restore drills.

## 8. Three repository responsibilities

- StrategyG/Universal-Generative-AI: canonical UGAI Core, reasoning, model routing, orchestration contracts and platform integration.
- StrategyG/im19-universal-mcp: MCP gateway, tool/provider adapters, credential vault and secure execution boundary.
- StrategyG/ai-notebook-studio-v: notebook/research workspace, datasets, experiments, evaluation and learning lifecycle.

GitHub is canonical for committed source. Cross-repository integration must use versioned API/event contracts and pinned commit/release references. No repository may assume another is deployed merely because its code exists.

## 9. Event and API contracts

Use versioned OpenAPI and JSON Schema contracts. Common event envelope:
event_id, event_type, schema_version, tenant_id, project_id, actor_id, source, correlation_id, causation_id, idempotency_key, occurred_at, aggregate_id, aggregate_version, payload.

Required event patterns include task created/transitioned, approval requested/decided, tool invoked/completed/rejected, evidence recorded, artifact registered, ingestion completed, evaluation completed, model candidate created/promoted/rejected, and backup/restore verified.

Use transactional outbox; consumers must tolerate duplicate delivery and reconcile from authoritative aggregate state. Avoid dual writes without an outbox or equivalent atomic handoff.

## 10. Delivery phases and gates

- P0 Audit/baseline: repository commit/branch/tree, dependencies, CI, test baseline, security, Supabase schemas/policies/migrations, VM/Drive access and architecture decisions.
- P1 Contracts/security: identity, tenant/object authorization, secret handling, audit, approval, outbox, API/event schemas and CI.
- P2 Reasoning foundation: model interface/router, evidence-aware reasoning, decision envelope, benchmark harness and local inference feasibility.
- P3 Knowledge: RAG migration plan, provenance, hybrid retrieval, graph and tenant isolation.
- P4 Workflow/agents: persistent state, DAG, leases, idempotency, bounded delegation and recovery.
- P5 IM19 execution: versioned MCP integration, tool policy, sandbox, approval and external-effect verification.
- P6 Notebook/learning: dataset provenance, experiments, independent evaluation and human promotion.
- P7 Quality/operations: adversarial tests, load, SLOs, observability, backup/restore and disaster recovery.
- P8 Production certification: staged/canary deployment, rollback, incident runbooks, signed evidence and human release approval.

A phase is not complete because code or documentation exists. Each gate requires reproducible test output, commit SHA, environment/configuration identity, logs/artifacts, reviewer and explicit PASS/FAIL/BLOCKED status.

## 11. Acceptance metrics (targets to calibrate, not current results)

Create versioned representative datasets before fixing numeric thresholds. Measure:
- reasoning: decision correctness, evidence support, calibration, abstention quality, counterargument coverage;
- RAG: Recall@k, nDCG@k, citation correctness, answer groundedness, no-evidence behavior;
- agents: task success, policy violation, duplicate side effects, recovery correctness;
- runtime: p50/p95 latency, throughput, error rate, VRAM/RAM, tokens/sec and cost/request;
- security: zero accepted cross-tenant access in adversarial tests, zero unapproved high-impact actions, no secret disclosure;
- operations: availability, queue age, backup freshness, restore success, RPO/RTO.

Every metric requires dataset/version, sample size, method, baseline, environment, confidence interval where applicable, and date. Targets are not achievements.

## 12. P0 evidence snapshot (2026-11-04)

Observed through connected GitHub and Supabase integrations:
- Universal-Generative-AI default branch main; README describes initialization only; latest visible commit is documentation initialization. No production capability is claimed.
- im19-universal-mcp default branch main; README documents a 0.3.0 read-only gateway baseline, approval-gated Drive folder prototype disabled by default, and deployment acceptance still pending. Latest visible commit adds a fail-closed outbound MCP router core.
- ai-notebook-studio-v default branch main; README describes V5 foundation and V6 identity feature work. Stage 1 is partial; DB migration/RLS tests and several integrations remain not run/not implemented. Production status is NO-GO.
- Supabase project institutional-rag is ACTIVE_HEALTHY, PostgreSQL 17, region ap-southeast-1. Migration history includes RAG retrieval, provenance, review, knowledge synthesis and embedding gates through migration 20261103051537.
- Supabase advisor reported 21 RLS-enabled/no-policy findings in schema institutional_rag; direct catalog inspection showed 21 tables with RLS enabled and zero policies, while four tables in schema rag each have one policy. This is a high-priority access-model review, not by itself proof of external exposure or a confirmed data leak. Verify schema exposure, grants, function execution paths and intended service-only access before changing policies.
- Supabase performance advisor reported 10 unused-index informational findings; do not drop indexes without workload evidence.
- PostgreSQL VM and Google Drive operational access were not available in this audit; their state, backup freshness, restore capability and network/security posture remain UNKNOWN.

This snapshot is a point-in-time audit record, not a production certification. Re-run before implementation decisions that depend on mutable state.

## 13. Immediate P0 remediation queue

1. Inspect Supabase schema exposure, grants, RLS policies, SECURITY DEFINER functions and service-role call paths; resolve the 21 findings based on intended access.
2. Capture complete repository trees, branch/PR/CI status, dependency inventories, licenses, test commands and latest commit SHAs.
3. Reconcile README status claims with merged commits and CI evidence, especially AI Notebook Studio V6 and IM19 deployment readiness.
4. Obtain read-only VM inventory: PostgreSQL version, extensions, backup configuration, TLS, firewall, roles, disk/CPU/RAM, monitoring and restore procedure.
5. Obtain Google Drive backup inventory: folder ownership, encryption, retention, object hashes, versioning, backup logs and restore test.
6. Define per-domain data ownership and migration manifests before any replication or DDL.
7. Establish reproducible baseline tests and evidence records for all three repositories.

## 14. Change control

Do not write to production Supabase, migrate/cut over data, rotate credentials, deploy, merge protected branches, or enable provider mutations as part of an audit. Implement through isolated branches and reviewed pull requests. Record every external side effect and verify it against its owning system.

**Current decision:** Architecture approved as target. P0 audit is PARTIAL. UGAI V3.0 implementation readiness and production readiness are NOT VERIFIED.

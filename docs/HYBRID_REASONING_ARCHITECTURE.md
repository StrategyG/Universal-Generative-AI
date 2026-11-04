# UGAI Hybrid Model & Reasoning Architecture

**Document ID:** UGAI-AI-ARCH-002  
**Version:** 1.0.0-draft  
**Status:** Approved architecture direction; implementation and acceptance pending  
**Priority:** Reasoning intelligence  
**Parent baseline:** `docs/MASTER_ENGINEERING_SPECIFICATION.md`  
**Model router baseline:** `upgrade/universal-model-platform-v1`

> This document specifies the target and staged implementation. A provider route, reasoning stage, benchmark, or integration is not considered implemented until code, exact-SHA tests, and runtime evidence demonstrate it.

## 1. Decision

UGAI adopts a **hybrid multi-provider model architecture**. It does not require training a foundation model and does not imply multi-agent autonomy. Multiple model providers and model classes are selected behind one provider-neutral control plane according to task requirements, declared capabilities, risk, latency, context limits, availability, and cost policy.

Reasoning is the first optimization priority. Supabase remains active and authoritative during implementation. A self-managed PostgreSQL VM is a hybrid replication/DR target, not an automatic replacement. Google Drive remains an encrypted backup/archive destination. The three product planes retain separate ownership:

- **UGAI — Intelligence & Control Plane:** request understanding, model routing, reasoning orchestration, evidence/RAG policy, evaluation, decision policy, approvals, durable workflow and audit.
- **IM19 MCP — Tool Plane:** authenticated MCP gateway, provider/tool discovery, tenant-bound authorization, secrets, quotas, outbound policy and redacted tool audit. It does not decide business outcomes.
- **AI Notebook Studio — Execution Plane:** notebook sessions and isolated computation. It does not independently authorize privileged tools or production changes.

## 2. Model roles

Model roles are logical capabilities, not hard-coded vendor names. Each deployment maps approved immutable provider/model/revision identifiers to these roles.

| Role | Purpose | Default selection |
|---|---|---|
| `reasoning_primary` | Complex analysis, synthesis, planning and decision support | Highest approved reasoning quality within task budget |
| `reasoning_fallback` | Continue a request when primary is unavailable before output commitment | Explicitly approved compatible route |
| `independent_evaluator` | Critique evidence, assumptions, logic and proposed conclusions | Different model family/provider where practical |
| `fast_classifier` | Intent, task class, risk and routing metadata | Low-latency/low-cost model |
| `embedding` | Query/document vectorization | Version-pinned embedding model |
| `reranker` | Rank candidate evidence passages | Version-pinned reranker |
| `multimodal_reader` | Extract evidence from images/audio/documents where required | Explicit modality-capable model |

No route is assumed to support tool calling, JSON schema, vision, audio, or long context merely because it uses an OpenAI-compatible API. Each adapter declares capabilities and passes adapter-specific contract tests.

## 3. Routing policy

Routing is server-owned and policy-driven. The caller may express a task objective and constraints but cannot select an unapproved provider, override tenant policy, increase its own budget, or downgrade risk.

Routing inputs:
- task class and complexity;
- data classification and tenant/project scope;
- required capabilities and context window;
- approved model ID and immutable revision;
- latency and token/cost budgets;
- provider health and quota state;
- reasoning depth profile: `standard`, `deep`, or `critical`;
- output contract and evaluation requirement.

Routing order:
1. Authenticate actor and resolve tenant/project from trusted claims.
2. Classify request and determine risk server-side.
3. Retrieve only authorized context and evidence.
4. Filter the registry to approved routes satisfying capability, region/data policy and budget.
5. Select the lowest-cost route that meets the quality/risk policy; high-impact decisions require the approved reasoning route plus independent evaluation.
6. Retry transient failures only within bounded policy. Fallback is permitted only before a response is committed; never splice partial generations.
7. Record provider/model/revision, policy version, latency, usage and sanitized outcome metadata.

Unknown route, missing revision, budget exhaustion, policy failure or unsupported capability fails closed.

## 4. Reasoning pipeline

Reasoning is an orchestrated sequence of bounded, typed tasks. It is not a claim that hidden model reasoning can be inspected or verified. Do not request, store, expose or score private chain-of-thought. Store concise rationale summaries, evidence references, assumptions, uncertainty, alternatives and verification results.

1. **Observe:** normalize objective, constraints, actor and context.
2. **Analyze:** decompose the problem; identify causal, logical and quantitative questions.
3. **Retrieve:** obtain tenant-authorized evidence with source IDs, timestamps, hashes and provenance.
4. **Evaluate:** assess source reliability, relevance, freshness, independence and contradictions.
5. **Challenge:** produce strongest counterarguments, missing evidence and falsification tests.
6. **Synthesize:** reconcile supported claims; label unresolved conflicts and unknowns.
7. **Decide:** compare options using explicit criteria, risk tolerance, reversibility and expected value where measurable.
8. **Verify:** run deterministic checks, tool evidence checks or independent evaluator review.
9. **Respond / request approval:** return a grounded answer or a bounded execution plan. High-impact actions require human approval and a matching, unexpired approval receipt.

The pipeline may skip stages for low-risk requests. It must deepen evaluation for high-impact, uncertain, conflicting or irreversible decisions.

## 5. Typed reasoning artifact

Every completed reasoning task should produce a versioned artifact containing:
- `request_id`, `tenant_id`, `project_id`, `policy_version`;
- task class, risk tier and reasoning profile;
- selected model role, provider, model ID and revision per stage;
- objective, constraints and explicit assumptions;
- claims linked to evidence IDs and source provenance;
- counterarguments, contradictions and unresolved questions;
- options and evaluation criteria;
- uncertainty/confidence calibration fields (not unsupported self-reported certainty);
- concise rationale summary, conclusion and limitations;
- verification status and evaluator findings;
- proposed action plan, idempotency key and approval requirement;
- token/cost/latency metadata and trace correlation.

Never place API keys, access tokens, raw credentials, unrestricted prompts, private chain-of-thought or sensitive source payloads in audit events.

## 6. Knowledge and data architecture

Supabase remains the live system of record for current RAG and application data until an explicit, verified cutover decision. PostgreSQL VM is a separate hybrid replica/DR target. Google Drive is encrypted backup/archive, not a transactional database.

- RAG retrieval must enforce tenant/project authorization before returning passages.
- Evidence provenance is preserved through retrieval, reranking, synthesis and decision artifacts.
- Embedding model and dimensions are versioned; incompatible vectors are not silently mixed.
- Hybrid replication uses idempotent events, checkpoints, replay protection, quarantine and reconciliation.
- Backups are encrypted, checksummed, retention-controlled and restore-tested.
- No migration, production DDL, source data write, service pause or traffic cutover is implied by this specification.

## 7. Three-plane contracts

- UGAI calls IM19 through authenticated remote MCP with a scoped service identity, exact resource audience, allowlisted tools and pre/post audit.
- UGAI sends Studio tasks using versioned HTTPS APIs, tenant/actor-bound tokens, idempotency, bounded schemas and explicit task-state transitions.
- IM19 and Studio return structured receipts and artifact references; UGAI validates identity, tenant, correlation, digest and policy before accepting results.
- Studio execution must use a real OS/container isolation boundary for untrusted code. AST filtering alone is insufficient.
- Tool execution, notebook execution, external writes and production deployment are separate permission domains.

## 8. Security and governance

- Secrets are injected from a secret manager; no production default signing keys.
- Model output is untrusted input and cannot grant permissions.
- Prompt injection in retrieved documents and tool output is treated as data, never policy.
- Tenant identity is sourced from verified server-side identity claims, not user-editable metadata.
- High-impact decisions require independent evaluation and human approval.
- Provider fallback, data residency, retention and model-training/data-use policies are explicit registry attributes.
- All model and tool calls have bounded timeout, token budget, concurrency, retry and quota controls.
- Redacted logs contain correlation and operational metadata, not raw prompts or credentials.

## 9. Staged implementation and gates

### H0 — Baseline and contracts
- Reconcile existing provider router PR with this role model.
- Publish typed reasoning artifact and routing-policy contracts.
- Inventory approved provider/model IDs, immutable revisions, capabilities, cost and data policy.
- Exit: schema validation and contract tests; no provider claims without evidence.

### H1 — Reasoning runtime
- Add server-owned task classifier and policy-aware role router.
- Implement bounded Observe/Analyze/Retrieve/Evaluate/Challenge/Synthesize/Decide/Verify orchestration.
- Add independent evaluator path for critical/high-risk tasks.
- Exit: deterministic stage lifecycle tests, fail-closed routing tests, no chain-of-thought persistence.

### H2 — Evidence-grounded reasoning
- Connect authorized RAG retrieval and reranking.
- Require claim-to-evidence mapping, source independence and contradiction handling.
- Exit: retrieval and grounded-answer benchmark passes; tenant-isolation tests pass.

### H3 — Three-plane execution
- Connect UGAI to IM19 and Studio via versioned contracts.
- Enforce approval receipts, idempotency, durable task state and artifact verification.
- Exit: staging E2E with live identities and no mocked service boundary.

### H4 — Hybrid persistence and resilience
- Keep Supabase authoritative; enable PostgreSQL VM replication and encrypted Google Drive backup.
- Validate replay, conflict quarantine, checksums, restore and rollback.
- Exit: measured RPO/RTO and independent restore drill; no data divergence.

### H5 — Production qualification
- Run quality, safety, security, latency, cost, load and resilience benchmarks on exact release SHAs.
- Canary with rollback and human release approval.
- Exit: all mandatory release gates PASS; otherwise NO-GO.

## 10. Non-goals and prohibited shortcuts

- No fine-tuning or foundation-model training before benchmark evidence shows it is necessary.
- No unrestricted model-issued tool calls or model-controlled approval.
- No majority vote as a substitute for source independence or evidence quality.
- No confidence score accepted without calibration against labeled outcomes.
- No production claim from mocked tests, documentation, provider catalog visibility or local simulation.
- No automatic Supabase shutdown or PostgreSQL cutover.

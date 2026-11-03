# Full Transformation Plan and Validation Gates

Status: Roadmap. Phases are not complete until evidence is attached.

## Current release status (verified 2026-11-03)

The Supabase `production_release_decision_v1` currently reports `NO_GO`: 2/9 technical gates passed and 0/4 operational gates passed. The readiness view reports zero attested embedding artifacts, zero completed staging embeddings meeting the verified-model gate, zero qualified independent human reviewers, zero formally approved/published cited excerpts, zero independently authored 50-question evaluation sets, and zero complete 50-case evaluation runs. AI triage is advisory only (528 observed), and the hold/index alignment gate passes (293/293). The source catalog currently has 432 discovered and 2 chunked source documents; do not describe the corpus as fully indexed.

This release decision is authoritative for the current project state. Do not enable production Agentic Hybrid RAG or label the system production-ready until all P0/P1 gates and operational attestations pass.

## Phase 0 — Baseline and safeguards

- Preserve current `main`; work in a feature branch and use pull requests.
- Pin repository baseline and record Supabase migration head.
- Snapshot schema, grants, RLS policies, RPC signatures/definitions, Edge Function version/secrets metadata, and current advisor output.
- Add automated baseline checks; do not mutate production data during discovery.

Exit: reproducible baseline report and rollback plan.

## Phase 1 — Security and service boundary

- Harden Edge Function authentication and secret rotation.
- Add bounded streaming body parser, rate limiting, request IDs, and structured audit logs.
- Review API schema exposure, grants, function EXECUTE permissions, and service-role usage.
- Preserve the current approved keyword retrieval path while introducing a versioned adapter contract.

Exit: negative auth tests pass; body size and rate limits enforced; no secret leakage; existing retrieval compatibility test passes.

## Phase 2 — UGAI foundation

- Choose and document runtime/framework after explicit technical fit review; do not infer stack from an empty repository.
- Build configuration validation, provider interfaces, model registry, request/error contracts, and health/readiness.
- Add unit tests and CI for lint, typecheck, tests, dependency audit, and build.

Exit: clean install, deterministic test suite, CI green, no hardcoded secrets.

## Phase 3 — Retrieval integration

- Keep Supabase PostgreSQL + pgvector as the active primary vector backend; keep the legacy and Institutional corpora separate.
- Use the Institutional RAG service adapter for governed evidence; do not query staging tables directly from the chat path.
- Keep a provider-neutral VectorStore interface. Astra DB remains an optional future adapter and must not become a second evidence authority.
- If an external vector index is introduced later, populate it through a durable outbox/projector and revalidate every candidate against Supabase before citation.
- Use query-planning schemas, per-subquestion retrieval budgets, hybrid lexical/vector retrieval, RRF within corpus/tier, and evidence/claim ledgers.

- Implement RAG client adapter and typed evidence model.
- Keep legacy `rag` and `institutional_rag` as separate corpora.
- Keep approved and staging retrieval isolated.
- Introduce approved hybrid search only after model attestation and published-evidence eligibility are satisfied.
- Add fusion, optional reranking, metadata filters, source deduplication, citation resolver, and retrieval tracing.

Exit: retrieval evaluation set passes; no staging evidence in production path; source hash and page locator checks pass.

## Phase 4 — Agentic orchestrator

- Implement intent classifier, planner schema, plan validator, bounded scheduler, tool registry, and policy engine.
- Support multi-step decomposition, retrieval retries, evidence sufficiency checks, calculations, and synthesis.
- Enforce max steps, tool calls, tokens, cost, concurrency, and wall-clock duration.
- Require human confirmation for consequential actions.

Exit: workflow tests pass for simple QA, multi-document comparison, numeric analysis, conflicting sources, insufficient evidence, and prompt injection.

## Phase 5 — Knowledge intelligence

- Build explicit entity/relation extraction and source-backed graph candidates.
- Keep candidate graph and synthesis private until existing human approval and publication gates pass.
- Support political, business, scientific, technical, and operational domains through metadata and task templates, not hard-coded conclusions.
- Add temporal validity, source reliability, contradiction tracking, and claim-level provenance.

Exit: every published node/edge has source provenance, review status, and reproducible promotion audit.

## Phase 6 — Multimodal and artifact workflows

- Add image, document, audio/video, 3D, and artifact jobs through provider/tool adapters.
- Isolate parsers and renderers; use job queue for long-running tasks.
- Store artifacts with ownership, checksum, MIME, retention, and signed access.
- Connect generated artifacts to knowledge only when explicitly indexed and approved.

Exit: upload and job limits, malware/parser tests, cancellation, retries, artifact integrity, and cost controls pass.

## Phase 7 — Production hardening

- Add tracing, metrics, dashboards, alerting, backup/restore, disaster recovery, and runbooks.
- Add load, soak, chaos, and recovery tests.
- Conduct independent security review and data-protection review.
- Deploy via canary/blue-green with rollback.

Exit: all release gates pass and operational owner signs off.

## Minimum quality gates

| Dimension | Gate |
|---|---|
| Install/build | Reproducible from clean checkout |
| Tests | Unit + integration + negative + workflow tests |
| Retrieval | Recall@k, MRR/nDCG, citation precision and recall |
| Grounding | No unsupported citation claims in benchmark |
| Security | AuthZ, RLS, prompt injection, SSRF, upload and secret tests |
| Reliability | Timeouts, bounded retries, circuit breaker, graceful degradation |
| Cost | Per-user and per-workflow budget enforcement |
| Operations | Health/readiness, logs, traces, metrics, backup and rollback |

Do not claim a production-readiness score until these gates are measured. The current repository is documentation-only and has no executable application stack.

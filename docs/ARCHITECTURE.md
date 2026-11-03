# Hybrid Institutional Intelligence Architecture

Status: Proposed architecture; documentation only. No runtime capability is implied by this document.

## Decision

Use a hybrid architecture with three independently deployable boundaries:

1. **Universal Generative AI (UGAI):** product/API surface, model-provider gateway, multimodal generation, artifact lifecycle, workflow execution.
2. **Institutional RAG:** authoritative knowledge and evidence service backed by the existing Supabase project. It owns ingestion, provenance, retrieval eligibility, citation metadata, evaluation, and human-governed publication.
3. **Intelligence Orchestrator:** coordinates planning, bounded retrieval, tool execution, synthesis, verification, and final response assembly. It calls the other services through versioned contracts and does not own source-of-truth knowledge.

The orchestrator may initially be a module inside UGAI. Keep its interfaces deployable as a separate service later.

## Current-state facts verified on 2026-11-03

- UGAI default branch `main` contains only `README.md`; the README says initialization only and explicitly says planned features are not implemented.
- Supabase project has PostgreSQL 17 and pgvector 0.8.2.
- Legacy `rag`: 383 documents and 26,186 chunks. Semantic retrieval checks 384-dimensional normalized vectors and the `intfloat/multilingual-e5-small` model.
- `institutional_rag`: 434 source documents and 1,109 chunks; current source status query shows 432 `discovered` and 2 `chunked`, so this count is not equivalent to 434 indexed/approved sources. It contains evidence review, embedding attestation, evaluation, web evidence staging, knowledge relation staging, and synthesis staging.
- Live `production_readiness_v1` reports `NO_GO`: 2 of 9 technical gates pass and 0 of 4 operational gates pass. Critical unmet gates include attested embedding model, 30 verified staging embeddings, two independent real reviewers, at least one approved/published cited excerpt, and 50 independently authored/scored evaluation cases.
- The current evaluation inventory has 34 active cases and 38 result rows; this is not the required independent 50-case release evaluation.
- `institutional_rag.search_staged_hybrid_v1` is explicitly marked `UNAPPROVED_INTERNAL_RESEARCH_ONLY`. It is not a production answer retrieval path.
- Active Edge Function `institutional-rag-search` is version 4, uses custom `x-rag-api-key` authentication, has `verify_jwt=false`, and currently calls `public.im19_match_trusted_v1` (approved keyword retrieval).
- 21 institutional tables have RLS enabled with no policies; service-role grants exist for operational access. Do not add broad policies merely to clear advisor findings.

Revalidate these facts before implementation because database and repository state can change.

## Logical architecture

```text
Client / Notebook / API
        |
        v
UGAI API Gateway
  - AuthN/AuthZ, quotas, request IDs
  - Conversation and artifact APIs
  - Provider registry and model router
        |
        v
Intelligence Orchestrator
  - Intent and risk classification
  - Plan compiler (strict schema)
  - Retrieval policy decision
  - Bounded agent/tool scheduler
  - Evidence/context assembler
  - Claim and citation verifier
        |                         |
        |                         +--> AI provider adapters
        |                               chat / stream / embeddings
        |
        +--> Institutional RAG API
               - approved retrieval
               - citation-safe source metadata
               - evaluation and feedback
               - no direct model execution
        |
        +--> allowlisted tools
               - calculations
               - document transforms
               - image / 3D / video jobs
               - external MCP connectors
        |
        v
Response + citations + trace + usage
```

## Source-of-truth boundaries

- Supabase owns document/source identity, source hashes, page locators, chunk provenance, embedding model attestation, evidence review state, and publication gates.
- UGAI owns user-facing conversations, generation jobs, provider configuration references, artifacts, and orchestration traces.
- The orchestrator owns ephemeral plans and intermediate workflow state. Persist only auditable plan summaries, tool inputs/outputs, evidence IDs, and final results; do not persist hidden chain-of-thought.
- Provider adapters own provider-specific request/response translation. They must not bypass orchestrator policies.
- No component may promote staged knowledge or approve evidence on behalf of a human reviewer.

## Retrieval tiers

1. **Published/approved evidence:** eligible for user-facing factual claims, subject to current citation and source-integrity checks.
2. **Trusted citation-safe excerpt:** may be used only within the scope declared by the approved retrieval RPC and its metadata.
3. **Private staging/research:** may inform internal research workflows only when explicitly enabled; must be labelled provisional and must never be represented as approved evidence.
4. **Unverified web capture / AI synthesis / graph edge:** candidate material, not authoritative evidence.

Never blend tiers into a single unlabelled result set. Every result carries `evidence_tier`, `review_status`, `trusted`, `source_hash`, `locator`, and retrieval method.

## Model roles

- Chat/reasoning model: planning, synthesis, analysis, final answer.
- Small/fast model: classification, query rewrite, extraction, title generation.
- Embedding model: retrieval vector generation; dimension and model artifact must match the approved index.
- Reranker: optional ranking of retrieved candidates; cannot upgrade evidence trust.
- Verifier: checks claim-to-source support and citation integrity; cannot manufacture missing evidence.

Model selection is policy-driven by task capability, privacy class, context limit, latency, availability, and cost. Provider fallback is allowed only when the replacement model satisfies the same task and data-handling policy.

## Reliability and safety invariants

- Fail closed on missing authentication, unknown tenant, unavailable authorization context, or unapproved retrieval scope.
- Never pass service-role credentials or provider API keys to clients or model prompts.
- Treat retrieved documents, tool outputs, and web captures as untrusted data, never as instructions.
- Validate planner output against a strict schema and server-side allowlist.
- Bound steps, tool calls, concurrency, wall-clock time, bytes, tokens, and cost per workflow.
- Require explicit approval for consequential or destructive actions.
- Citations must resolve to immutable source/chunk identifiers and exact page/section locators.
- If evidence is insufficient, say so; do not fill gaps with model memory while implying RAG support.

## Deployment topology

Start with a modular monolith for UGAI plus a separately protected Supabase RAG service. Keep HTTP contracts versioned so the orchestrator can later be extracted. Do not introduce Kafka, Kubernetes, a graph database, or another vector store until measured load or capability requirements justify them.

## Explicit non-goals for the first release

- No migration or consolidation of the two existing RAG schemas.
- No direct client access to private schemas.
- No auto-publication of AI-generated knowledge.
- No assumption that staging hybrid search is approved.
- No automatic execution of arbitrary MCP tools or generated SQL.

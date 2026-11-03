# Reference Architecture — Hybrid Institutional Intelligence

**Specification status:** design baseline, not deployed runtime.  
**Verified platform snapshot:** 2026-11-03.  
**Target deployment:** UGAI modular application + independently governed Supabase Institutional RAG.

## 1. Architectural decisions

| Decision | Selection | Reason / constraint |
|---|---|---|
| Topology | Hybrid | Application/orchestration lifecycle independent from knowledge governance. |
| Initial application shape | Modular monolith | Avoid distributed-systems overhead before throughput requires extraction. |
| Backend baseline | Python 3.12 + FastAPI (proposed default) | Strong document/AI ecosystem; validate against deployment and team constraints. |
| Contracts | Pydantic + JSON Schema | Strict input/output boundaries and versioned payloads. |
| Persistence | Supabase PostgreSQL, isolated schemas | Reuse managed database while preserving ownership boundaries. |
| Retrieval storage | Existing pgvector + PostgreSQL FTS | No new vector database until measured evidence requires it. |
| Fusion | RRF, within each corpus | Combines rank positions without pretending raw scores share a scale. |
| Orchestration | Bounded DAG/state machine | Explicit dependencies, retry, timeout, cancellation, and audit behavior. |
| Long-running work | Durable job records + worker | Do not keep HTTP requests open for ingestion or multimodal generation. |
| Streaming | Server-Sent Events | Incremental output and workflow status. |
| Deployment | Containerized service + CI | Reproducible runtime and release gates. |

Python/FastAPI is the proposed default, not an existing repository fact. Changing runtime requires a recorded architecture decision.

## 2. System context and trust zones

### Zone A — Untrusted clients
Web UI, notebooks, CLI, and external API consumers. Treat request bodies, uploads, URLs, tool parameters, and client metadata as untrusted.

### Zone B — UGAI application trust boundary
Owns authentication, tenant authorization, conversation API, orchestration, provider routing, job scheduling, artifacts, policy evaluation, and response verification. No service credential is sent to the client.

### Zone C — Institutional Knowledge service
Supabase Edge Function and database RPCs. Owns source identities, source hashes, page/section locators, chunks, embedding provenance, evidence review, publication, retrieval eligibility, and evaluation evidence. It is not the model planner and must not execute arbitrary model instructions.

### Zone D — External providers and tools
LLM vendors, embedding providers, rerankers, web fetchers, MCP servers, and media renderers. Each is an explicit egress boundary with capability allowlists, privacy policy, timeout, quota, and output validation.

## 3. Component decomposition

### 3.1 API Gateway
Responsibilities:
- Authenticate caller and resolve tenant/principal from verified identity.
- Authorize conversation, knowledge corpus, tools, and artifact access.
- Enforce request byte limit, per-principal quotas, concurrency, idempotency, and request IDs.
- Normalize errors and redact sensitive response headers.
- Expose /v1/responses, /v1/responses/{id}, /v1/responses/{id}/events, /v1/jobs/{id}, and /v1/artifacts/{id}.

Must not:
- Accept client-provided trusted=true, review_status=approved, or internal tenant scope as authoritative.
- Accept arbitrary SQL, filesystem paths, or arbitrary MCP URLs.

### 3.2 Conversation and Context Service
- Store user-visible conversation messages and explicit memory summaries.
- Apply retention and data classification.
- Build compact context from recent messages and approved memory.
- Keep retrieved evidence separate from conversation history.
- Do not persist hidden chain-of-thought.

### 3.3 Model Gateway
Stable interfaces:
- ChatModel.generate(request) -> ModelResult
- ChatModel.stream(request) -> AsyncIterator[ModelEvent]
- EmbeddingModel.embed(texts) -> EmbeddingBatch
- Reranker.rerank(query, candidates) -> RankedCandidates

Provider registry fields:
provider ID, model ID, capabilities, context limit, supported modalities, privacy class, region, timeout, rate-limit profile, cost profile, enabled state, fallback group, adapter version.

A provider may be selected only if it supports the task, is approved for the data classification, satisfies context/output limits, has budget headroom, and is healthy. Fallback must satisfy the same privacy and capability policy.

Never log API keys, Authorization headers, raw secrets, or unredacted provider payloads.

### 3.4 Intelligence Orchestrator
Modules:
- intent and domain classifier;
- risk and privacy classifier;
- task planner;
- plan schema validator;
- retrieval policy resolver;
- bounded DAG executor;
- tool registry and permission engine;
- evidence assembler;
- claim extractor and citation validator;
- response composer;
- trace and cost recorder.

The planner may propose work. The policy engine decides what is permitted. The executor runs only validated steps. The verifier determines whether output can be represented as evidence-grounded.

### 3.5 Institutional RAG Adapter
The adapter is the only UGAI component that knows Supabase Edge Function paths and RPC response shapes. It normalizes raw results into EvidenceRecord.

Separate operations:
- retrieve_approved_institutional
- retrieve_legacy_rag
- retrieve_private_research (privileged, explicit opt-in)

No automatic corpus merge until authorization and ranking have been evaluated together.

### 3.6 Tool Runtime
Tools are registered capabilities, not arbitrary function calls. Each definition specifies:
- stable name and version;
- argument and result JSON Schemas;
- minimum role/scope;
- data classification;
- idempotency behavior;
- side-effect class;
- confirmation requirement;
- timeout, maximum result bytes, and concurrency;
- network and destination allowlist.

### 3.7 Artifact Service
Stores uploads and generated outputs with owner/tenant ID, checksum, MIME, file size, retention, creation source, job ID, scan status, and access policy. Use short-lived signed URLs. Do not store executable uploads inside application code directories.

## 4. Control plane versus data plane

**Control plane**
- provider registry and model policies;
- tool registry and permission policies;
- corpus allowlist and retrieval tier mapping;
- evaluation suites and release gates;
- quotas, budgets, and feature flags;
- tenant/privacy policy.

**Data plane**
- request and conversation execution;
- retrieval and evidence;
- model/tool calls;
- jobs and artifacts;
- response and citations.

Control-plane changes require review, audit, versioning, and rollback. User content must never mutate control-plane policies.

## 5. Persistence ownership

Use separate logical schemas after migration review:
- institutional_rag: existing authoritative knowledge/evidence lifecycle; no casual schema refactor.
- rag: existing legacy corpus; retain as separately identifiable source.
- ugai: proposed application-owned records for conversations, workflow runs, steps, tool invocations, provider usage, artifacts, idempotency keys, and audit events.

Proposed ugai tables are not installed by this specification. A separate migration must define ownership, RLS, grants, retention, and indexes. If database co-location becomes a security or workload concern, move the application state store independently without changing the RAG contracts.

## 6. Canonical identifiers

- request_id: one inbound HTTP request.
- conversation_id: one conversational thread.
- workflow_id: one orchestrated run.
- step_id: one planned task step.
- attempt_id: one execution attempt for a step.
- evidence_id: immutable identifier of a retrieved excerpt/record.
- source_id: source document identity.
- artifact_id: immutable artifact record.
- tool_invocation_id: one tool execution record.
- provider_request_id: provider trace identifier where available.

Never overload UUID fields with provider IDs or human-readable names.

## 7. Deployment and failure domains

Initial deployment can be a single UGAI API process plus durable worker process, sharing application modules and versioned contracts. Supabase remains a separately protected service. Provider adapters execute behind outbound policy.

Scale API and workers independently. A slow video render must not exhaust interactive chat concurrency. Retrieval failures degrade to explicit no-evidence or an authorized fallback corpus, not an ungrounded claim.

## 8. Architectural invariants

1. Retrieval relevance and evidence trust are separate dimensions.
2. A model cannot approve evidence or grant itself permissions.
3. A tool cannot be called without server-side policy authorization.
4. Staging knowledge cannot enter normal production citations.
5. Source hash and locator must survive retrieval, synthesis, and final response.
6. Provider fallback cannot violate privacy or capability restrictions.
7. Retries are bounded and idempotency-aware.
8. User-facing answers distinguish verified evidence, inference, and uncertainty.
9. Hidden chain-of-thought is not persisted or exposed as an audit artifact.
10. Production readiness is determined by evidence-backed release gates, not by architectural ambition.

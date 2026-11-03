# Modular Agentic RAG — Execution Specification

**Target architecture:** Supabase-first Hybrid Agentic RAG  
**Status:** specification only; no runtime workflow is claimed deployed.

## 1. Architecture decision and storage boundary

The current project already has PostgreSQL 17, pgvector, two RAG corpora, approved-evidence predicates, lexical retrieval, staged vector/hybrid retrieval, provenance, evaluation, and publication governance.

Therefore:
- Supabase Institutional RAG is the source of truth for institutional sources, evidence, approval, publication, and citations.
- Supabase pgvector is the primary vector backend in the initial deployment.
- PostgreSQL full-text search is the primary lexical backend.
- RRF fuses eligible candidates only within an explicitly authorized corpus and evidence tier.
- Legacy rag remains a separately labelled corpus.
- Astra DB is not assumed to exist. It may later implement a VectorStore adapter or a replica index, but it cannot become an independent evidence authority.

Do not dual-write an unreviewed copy of the current corpus to Astra DB. If a future performance or product requirement justifies it, use an outbox/projection pattern and revalidate every candidate against Supabase before it becomes citation-eligible.

## 2. Runtime components

1. API Gateway: authentication, authorization, limits, idempotency, request IDs.
2. Conversation Manager: message persistence, summary, context selection, retention.
3. Intent Analyzer: intent, language, domain, risk, privacy and RAG requirement.
4. Query Planner: sub-question decomposition and retrieval plan.
5. Policy Engine: caller scopes, corpus policy, evidence tier, tools, budget and human approvals.
6. Retrieval Coordinator: parallel lexical/vector/metadata retrieval through corpus-specific adapters.
7. Fusion and Reranker: rank candidates; never change trust or approval state.
8. Evidence Validator: source identity, content hash, page/section, review/publication and release state.
9. Context Builder: token budgeting and evidence packing.
10. Model Gateway: provider/model adapter, streaming, retry, fallback and cost.
11. Tool Runtime: allowlisted and schema-validated tools.
12. Claim/Citation Verifier: claim-to-evidence ledger, locator resolution and grounding checks.
13. Response Composer: final answer, caveats, citations and abstention.
14. Telemetry/Audit: trace, state, latency, usage, cost, evidence IDs and policy versions.

## 3. End-to-end execution

### Stage 0 — Request acceptance
- Generate request_id and trace_id.
- Validate JSON body and content bytes.
- Authenticate user/workload.
- Resolve tenant/principal from verified credentials.
- Authorize conversation and allowed knowledge scope.
- Apply idempotency key and quotas.
- Persist user message and workflow state.

Reject before model invocation when authentication or authorization fails.

### Stage 1 — Query understanding
Extract:
- primary intent: factual QA, lookup, summarize, compare, deep research, decision analysis, generation;
- language and requested output form;
- named entities, exact identifiers, dates, amounts and units;
- temporal scope and geographic/jurisdiction scope;
- negation, exclusions, and constraints;
- requested corpus/document/notebook scope, checked against server-side permissions;
- sensitivity class and action risk.

Do not discard exact phrases, proper nouns, numeric strings, version numbers, legal references, or negation during query rewriting.

### Stage 2 — Need-RAG decision
Use deterministic rules plus model classification:
- RAG is required for claims about user-provided documents, private corpora, internal facts, or source-specific requests.
- RAG is strongly preferred for current or specialized evidence.
- General reasoning may proceed without RAG only when policy allows and output is labelled as model knowledge/analysis rather than retrieved fact.
- A user can explicitly require or prohibit retrieval; prohibition does not authorize unsupported claims.

### Stage 3 — Query planning
Planner returns a typed RetrievalPlan:
- normalized original question;
- subquestions and parent-child relation;
- entities and exact phrases to preserve;
- temporal and metadata filters;
- allowed corpus/method per subquestion;
- evidence requirements;
- maximum retrieval iterations and budget;
- expected answer sections.

The server validates schema, permissions, DAG cycles, tool names, filters, result limits, and aggregate budgets. A model-generated plan cannot grant its own access.

### Stage 4 — Retrieval fan-out
For each subquestion:
1. Check allowed corpus and evidence tier.
2. Apply tenant/notebook/document filters before retrieval.
3. Run lexical retrieval for exact identifiers, names, codes and dates.
4. Run vector retrieval for semantic matches when a matching approved embedding profile exists.
5. Run structured metadata lookup for page, source, period, type or entity.
6. Run conversation memory search only in the current user's authorized scope.
7. Preserve backend, corpus and method labels for all candidates.

The same authorization and evidence eligibility predicates must be used by lexical and vector branches. If this cannot be proven, do not fuse the branches.

### Stage 5 — Fusion
- Deduplicate on stable evidence/chunk ID and source/page.
- Apply RRF within one corpus and evidence tier.
- Record component ranks and fusion parameters.
- Avoid mixing incomparable raw similarity scores.
- Add source diversity limits to prevent one long document from monopolizing context.
- Keep legacy and private staging candidates visibly separate.

RRF formula:
RRF(d) = Σᵢ 1 / (k + rankᵢ(d)).

Initial k=60 is a benchmark starting point, not a universal constant. Evaluate on independent labels.

### Stage 6 — Reranking
Optional reranker considers:
- semantic relevance to the subquestion;
- entity and exact phrase match;
- temporal fit;
- answerability and passage completeness;
- duplicate or near-duplicate content.

Reranking changes order only. It must not change review_status, publication_state, trusted, tenant scope, or user citation eligibility.

### Stage 7 — Evidence validation
Before context assembly, validate:
- stable evidence/source/chunk IDs;
- source content SHA-256 and indexed source SHA consistency;
- exact page or section locator;
- excerpt identity and size;
- review and publication status from a server-trusted source;
- embedding profile/model attestation when semantic retrieval was used;
- current release decision and evidence expiry/revocation;
- caller access scope.

The current Edge Function response does not return every review/publication field. The adapter must either receive server-derived eligibility metadata from a narrow RPC/view or use a separately checked gate snapshot. It must never infer these values from rank, endpoint name, or model output.

### Stage 8 — Evidence sufficiency
Assess each subquestion separately:
- Is there direct evidence for the requested claim?
- Are numeric inputs complete and units/periods aligned?
- Is temporal scope satisfied?
- Are contradictory sources present?
- Is the evidence tier allowed for this workflow?
- Is the citation locator precise enough?

If insufficient:
- refine one query while preserving exact terms and constraints;
- broaden or narrow metadata filters within caller policy;
- use an explicitly authorized alternative corpus;
- stop after the configured iteration/budget limit and report the evidence gap.

Do not treat repeated retrieval of the same source or multiple AI summaries of one source as independent corroboration.

### Stage 9 — Context building
Context priority:
1. governing system/policy instructions;
2. exact current user request;
3. verified conversation summary and required recent messages;
4. eligible evidence selected for the subquestions;
5. authorized tool results;
6. output-format instructions.

Each source excerpt is delimited as untrusted data. Retrieved text cannot override system/developer policy or authorize tools.

Budgeting:
- reserve tokens for system/policy and final output;
- reserve space for the user's question;
- pack evidence by subquestion coverage and source diversity;
- avoid truncating away source title, page locator, qualifiers, table headers or units;
- record omitted evidence IDs and reason;
- count tokens with the selected model's tokenizer where available, otherwise use a conservative estimate.

### Stage 10 — Generation and tool loop
Generate a draft from evidence and claim ledger. If a tool is proposed:
1. validate tool name against registry;
2. validate arguments against versioned schema;
3. check principal, scope, data class and side-effect class;
4. enforce timeout, output bytes, concurrency and cost;
5. require human confirmation for protected side effects;
6. execute server-side;
7. validate returned data and mark it untrusted;
8. append invocation and result reference to the workflow trace.

Tool loop count is bounded. No arbitrary SQL, shell, Python, filesystem path or MCP endpoint execution.

### Stage 11 — Claim and citation verification
For every factual claim:
- create claim_id and claim_type;
- attach one or more evidence IDs;
- check the source really entails or directly states the claim;
- check arithmetic against raw inputs and formula;
- preserve units, period, qualifiers and negative conditions;
- check citation locator and source hash;
- flag unsupported inference, outdated source, and contradiction.

LLM/NLI verifier scores are advisory. Deterministic ID/hash/locator checks are mandatory. A verifier model cannot create missing evidence or override the release gate.

### Stage 12 — Response and persistence
Return:
- answer;
- resolved citations;
- explicit assumptions/inferences;
- warnings and evidence gaps;
- workflow/request IDs;
- status and usage metadata where permitted.

Persist visible messages, final claim/citation references, plan summary, tool invocation records, model/provider IDs, token/cost counters, and trace. Do not persist hidden chain-of-thought.

## 4. Workflow templates

### Simple grounded QA
Understand → retrieve → validate → context → generate → verify → answer.

### Multi-document comparison
Decompose by metric/period/document → retrieve each branch → normalize metrics and units → compare → explain conflicts → verify each comparison → answer.

### Deep research
Decompose → multi-corpus retrieval under separate policies → source diversity → evidence validation → contradiction analysis → follow-up retrieval (bounded) → synthesis → human review where publication is requested.

### Decision analysis
Define objective/constraints → retrieve evidence → identify assumptions → calculate/scenario model → counterfactual/pre-mortem → verify facts and calculations → present options, risks, and triggers.

## 5. Initial runtime limits (configurable proposals)

| Control | Interactive | Deep research |
|---|---:|---:|
| Planner revisions | 1 | 2 |
| DAG steps | 8 | 20 |
| Concurrent branches | 3 | 5 |
| Retrieval calls | 3 | 8 |
| Tool calls | 3 | 12 |
| Retrieval refinement rounds | 1 | 2 |
| Step attempts | 2 | 3 |
| Wall time | 45 s | 180 s |
| Evidence tokens | 12k | 40k |

All are aggregate limits. Per-tenant quotas and model token/cost constraints may reduce them.

## 6. Failure semantics

- Auth failure → 401.
- Permission failure → 403.
- Invalid plan/filter → 400.
- No eligible evidence → explicit no_evidence result.
- RAG outage → retrieval_unavailable; no hidden model-knowledge substitution.
- Model outage → compatible policy-approved fallback or model_unavailable.
- Citation mismatch → reject citation and revise/abstain.
- Budget exhaustion → terminate bounded workflow.
- Conflicting evidence → retain both, explain date/source differences.

## 7. Required traces

Record request/workflow IDs, plan version/hash, state transitions, corpus/method, evidence IDs and tiers, fusion config, reranker version, provider/model ID, tool names/version and argument hashes, retries, latency, token usage, cost estimate, claim IDs, citation results, abstention reason and final status. Do not log secrets or full restricted content by default.

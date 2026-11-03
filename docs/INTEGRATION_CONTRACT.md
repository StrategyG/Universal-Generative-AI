# UGAI ↔ Institutional RAG Integration Contract

Status: Proposed contract. The paths below are target interfaces, not deployed endpoints.

## Storage and ownership decision

The concrete project uses Supabase PostgreSQL + pgvector as its active knowledge/vector backend. The existing Institutional RAG database remains authoritative for source identity, evidence status, review, publication, and citation provenance. Astra DB is not currently established as a project dependency. Keep a provider-neutral VectorStore interface, but do not add Astra DB or dual-write the corpus unless load/quality/privacy measurements justify a future adapter. If Astra DB is ever used as a candidate index, every returned candidate must be revalidated against Supabase before citation or user-facing context.

## Existing endpoint (verified)

The active Supabase Edge Function is `institutional-rag-search` v4. It authenticates with `x-rag-api-key`, has Supabase JWT verification disabled, and calls `public.im19_match_trusted_v1(p_query_text, p_match_count)`. The RPC filters for citation-safe, page-scoped excerpts. The function labels its retrieval mode `approved_keyword`, and the RPC applies citation-scope, page-locator, and source-hash checks. However, the live release-readiness view is `NO_GO` with zero formally approved/published cited excerpts. Treat the endpoint's label as a retrieval-method label, not proof that the overall corpus or service has passed production release gates. It is not full hybrid vector retrieval.

Do not silently change this endpoint's semantics. Introduce a versioned contract or adapter.

## Target endpoint

`POST /v1/knowledge/retrieve`

Request:

```json
{
  "query": "string",
  "request_id": "uuid",
  "scope": {
    "corpus": ["institutional_approved", "legacy_rag", "private_notebook"],
    "notebook_ids": ["authorized-notebook-id"],
    "document_ids": [],
    "knowledge_domains": [],
    "source_ids": [],
    "as_of": null
  },
  "strategy": "approved_keyword",
  "limit": 8,
  "include_excerpt": true
}
```

Rules:
- `query`: 1-2,000 UTF-8 bytes after normalization.
- `limit`: integer 1-10.
- `strategy`: enum; initial allowed value remains `approved_keyword` until an approved hybrid RPC and evaluation gate exist.
- Caller identity and tenant scope come from verified authentication, never from client-supplied owner IDs.
- Private notebook IDs are resource selectors only. The server intersects them with the caller's current membership/ACL before retrieval; tenant_id is never accepted as authority from the body.
- Unknown corpus, domain, or strategy is rejected.
- Private notebook retrieval is request-scoped and requires current notebook ACL checks.
- Private staging retrieval requires a separate privileged route and explicit research mode.

Response:

```json
{
  "request_id": "uuid",
  "status": "evidence_found",
  "retrieval": {
    "strategy": "approved_keyword",
    "corpora": ["institutional_approved"],
    "candidate_count": 8
  },
  "evidence": [
    {
      "evidence_id": "uuid-or-stable-id",
      "source_id": "uuid",
      "source_title": "string",
      "source_hash": "sha256",
      "locator": {"page_start": 3, "page_end": 3, "section": null},
      "excerpt": "string",
      "rank": 0.0,
      "evidence_tier": "approved",
      "review_status": "approved",
      "trusted": true
    }
  ],
  "warnings": []
}
```

The response must not expose internal credentials, unrestricted source paths, raw database errors, or private staging rows.

## Orchestrator contract

The orchestrator receives typed evidence, not raw database records:

- `EvidenceRecord`: immutable IDs, title, locator, source hash, excerpt, tier, review state, retrieval method, score.
- `RetrievalResult`: request ID, strategy, corpus scope, evidence list, warnings, elapsed time.
- `Citation`: evidence ID + source ID + locator + source hash.
- `ClaimSupport`: claim ID, supporting evidence IDs, support verdict, verifier version.

The final response references citation IDs that the server resolves. The model may propose citations but cannot invent source IDs or mark a source trusted.

## Hybrid retrieval rollout

Do not route production queries to the existing `search_staged_hybrid_v1`: it returns `UNAPPROVED_INTERNAL_RESEARCH_ONLY` and operates on pending/unpublished evidence.

A production hybrid path may be enabled only after:
1. The source corpus is approved/published under existing governance.
2. Embedding model ID, artifact hash, dimension (the reviewed staged function expects 384), normalization, and content hash are verified.
3. Keyword and semantic retrieval share identical authorization and evidence eligibility filters.
4. Fusion (RRF or calibrated weighted fusion) preserves evidence tier and provenance.
5. Evaluation cases cover exact entities, Indonesian and English, dates/numbers, negation, multi-hop questions, and adversarial documents.
6. Retrieval quality and citation correctness meet release thresholds.

## Chat completion contract

UGAI exposes its own `POST /v1/chat/completions` and streaming equivalent. It may call retrieval internally. It must not forward a client-provided `evidence_tier`, `trusted`, or `review_status` as authoritative.

A workflow trace should record request and conversation IDs, plan version and bounded step count, selected provider/model identifiers (not secrets), retrieval strategy and evidence IDs, tool names and validated argument hashes, token usage, latency, retries, fallback, cost estimate, final citation IDs, and verification outcome.

Do not store hidden chain-of-thought. Store concise, auditable plan summaries and decisions.

## Error contract

Use stable codes: `AUTH_REQUIRED`, `ACCESS_DENIED`, `INVALID_REQUEST`, `RETRIEVAL_UNAVAILABLE`, `NO_ELIGIBLE_EVIDENCE`, `MODEL_UNAVAILABLE`, `BUDGET_EXCEEDED`, `TOOL_DENIED`, `VERIFICATION_FAILED`.

Return safe messages and request IDs. Do not return SQL, stack traces, provider response bodies, or credential values.

# Institutional RAG Backend Mapping

**Snapshot:** live Supabase inspection, 2026-11-03.  
**Purpose:** document which existing database surfaces are usable for which workflow. This file does not alter Supabase.

## 1. Current data domains

| Schema | Main entities | Observed inventory | Role |
|---|---|---:|---|
| rag | documents, chunks, ingest_jobs, audit_events | 383 documents; 26,186 chunks | Legacy document corpus |
| institutional_rag | source_documents, document_chunks, embedding_jobs, knowledge_candidates, evidence_staging_index, review_quorum, ai_evidence_current_v1, embedding_model_approvals | 434 source docs; 1,109 chunks; 34 active evaluation cases | Evidence-governed institutional corpus |

Institutional source status query returned 432 discovered and 2 chunked. Do not treat source-document count as fully indexed count.

## 2. Strict Institutional retrieval call chain

Current Edge Function v4:
1. Receives request at institutional-rag-search.
2. Authenticates custom x-rag-api-key.
3. Reads SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY from server environment.
4. Calls public.im19_match_trusted_v1(p_query_text, p_match_count).
5. Wrapper calls institutional_rag.search_chunks.
6. The SQL path joins document_chunks, source_documents, knowledge_candidates, evidence_staging_index, review_quorum, ai_evidence_current_v1, and embedding_model_approvals.

The strict search predicate requires:
- knowledge candidate review_status=approved and published=true;
- evidence claim_review_status=approved and trusted=true;
- technical evidence matched to a local PDF page;
- at least two valid reviewer approvals and zero vetoes;
- current AI attribution review supports the excerpt;
- source and evidence hashes match;
- excerpt equals the chunk and is pinned to one exact page;
- embedding model is approved and human-attested;
- embedding metadata is verified, content hash matches, dimension is 384, and norm is within 0.98–1.02;
- approved scope is CITED_EXCERPT_ONLY.

The public wrapper adds valid source SHA-256, single-page locator, approved-scope metadata, and non-empty excerpt checks.

## 3. Response normalization limitations

The current Edge Function response mapping includes:
- chunk_id, document_id, title, source_path, chunk_index;
- page;
- citation text derived from title and page;
- relevance_score;
- excerpt truncated to 4,000 characters;
- content_sha256.

It does not currently expose explicit evidence_tier, review_status, publication_state, human quorum details, retrieval score method version, or embedding artifact metadata in each result. Do not infer these from result rank. Either:
1. extend the Edge Function response from a narrow trusted RPC/view that supplies server-derived eligibility metadata; or
2. keep the current endpoint contract intentionally narrow and let the trusted service wrapper attach an attested route/tier only after successful release gate verification.

Do not allow a client to submit these fields and do not synthesize trust flags from the model.

## 4. Production release gate must be independent

The live production_release_decision_v1 reports NO_GO (2/9 technical, 0/4 operational). The strict SQL predicate is necessary but does not prove every overall operational release gate passed.

Before user-facing production retrieval:
- check the release decision from a server-controlled source;
- fail closed when decision is not GO or evidence expires;
- record the gate snapshot/version used for the request;
- keep staging/research routes separate from production routes.

A route being active/reachable is not proof that it is production-approved.

## 5. Staging retrieval functions

The following functions are not production answer sources:
- institutional_rag.search_staged_hybrid_v1: semantic + lexical fusion, but returns UNAPPROVED_INTERNAL_RESEARCH_ONLY and filters pending/unpublished candidate knowledge.
- institutional_rag.search_staged_weighted_v1: pending local-page weighted keyword search.
- institutional_rag.search_rag_lexical_rrf_v1/v5: searches staged PDF, web evidence, and derived synthesis; result scopes include research-only and unapproved derived context.

Their usefulness is knowledge mining and review preparation, not user-facing fact citation.

## 6. Legacy retrieval mapping

Legacy rag.match_chunks_keyword:
- only indexed documents;
- page-aware chunks and active ingest generation rules;
- returns document, chunk, page, content hash, and lexical rank.

Legacy rag.match_chunks_semantic:
- requires 384-dimensional normalized query vector;
- validates stored embedding dimension and embedding model label intfloat/multilingual-e5-small;
- only indexed documents;
- page-aware active generation requirements.

Legacy results must remain labelled legacy_rag. They must not be represented as approved Institutional RAG evidence simply because they have a valid vector or page number.

## 7. RAG adapter interface

The UGAI adapter should expose three separate methods, not one ambiguous generic search:

- search_institutional_approved(query, limit, request_context)
- search_legacy_corpus(query, mode, limit, request_context)
- search_private_staging(query, mode, limit, research_scope)

Each returns a typed retrieval envelope with:
- request_id and backend version;
- corpus identity and retrieval method;
- evidence list;
- evidence tier and citation eligibility derived server-side;
- warnings and no-evidence reason;
- elapsed time and candidate/result counts.

Private staging must be excluded from the production citation resolver at both service and application layers.

## 8. Required integration tests

- Strict institutional result cannot appear while release gate is NO_GO.
- Empty strict result is represented as no eligible evidence, not as corpus-empty.
- A pending/staged result cannot be cast into approved tier by modifying response JSON.
- Legacy result keeps legacy corpus label.
- Page/hash mismatch invalidates citation.
- Embedding dimension/model/artifact mismatch is rejected.
- A source modified after indexing invalidates old citation until reconciliation.
- Service-role or Edge Function errors are redacted and mapped to stable application errors.

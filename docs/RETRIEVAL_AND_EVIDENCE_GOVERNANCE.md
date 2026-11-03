# Retrieval and Evidence Governance

**Status:** policy specification grounded in Supabase inspection on 2026-11-03.

## 1. Verified retrieval surfaces

| Surface | Observed behavior | Permitted initial use |
|---|---|---|
| public.im19_match_trusted_v1 → institutional_rag.search_chunks | Requires approved/published candidate, approved trusted excerpt, two valid reviewer approvals, no veto, source/page/hash match, AI attribution review, attested embedding model and verified 384-dimensional vector | Strict citation-safe retrieval only. Live release gate still says NO-GO and reports zero approved/published excerpts. |
| institutional_rag.search_staged_hybrid_v1 | Semantic + lexical RRF; requires 384-dimensional normalized query vector and exact approved model artifact hash; returns UNAPPROVED_INTERNAL_RESEARCH_ONLY and operates on pending/unpublished candidates | Private research/engineering evaluation only |
| institutional_rag.search_rag_lexical_rrf_v1 / v5 | Combines staged PDF evidence, web staged evidence, and derived synthesis; includes pending/research-only scopes | Private research only; not a production answer source |
| institutional_rag.search_staged_weighted_v1 | Weighted lexical search over pending local-page evidence | Private research only |
| rag.match_chunks_keyword | Legacy FTS for indexed, page-aware documents | Separate legacy corpus after service authorization and evaluation |
| rag.match_chunks_semantic | Legacy vector search validates 384 dimensions, normalization, intfloat/multilingual-e5-small, and indexed document state | Separate legacy corpus after service authorization and evaluation |

A function name containing hybrid, trusted, or RRF is not itself release approval. Authorization and trust come from the full database predicates and release policy.

## 2. Critical semantic distinction

Keep independent dimensions:
- relevance: how well a result matches a query;
- provenance_integrity: source hash, page, chunk and embedding consistency;
- review_state: whether required AI/human review stages completed;
- publication_state: whether governance authorized publication;
- authorization_scope: whether caller/workflow may access the record;
- freshness: whether source time is appropriate for the question.

A high RRF score cannot change review_state, publication_state, or authorization_scope.

## 3. Corpus routing

### A. Institutional approved corpus

Call only through the protected service interface. Keep current public.im19_match_trusted_v1 adapter semantics. Validate every returned row:
- non-empty immutable chunk/source IDs;
- valid SHA-256 source checksum;
- one exact page locator (page_start >= 1 and page_end = page_start);
- non-empty bounded excerpt;
- source and chunk IDs resolve;
- result eligible under current approved retrieval policy.

A zero-row response means “no eligible evidence returned”, not “the answer does not exist in the complete corpus”. The live release view reports zero approved/published cited excerpts, so current general user-facing grounded coverage is not demonstrated.

### B. Legacy corpus

Keep legacy records labelled legacy_rag. It has a different ingestion model and source identity shape. Normalize outputs to common EvidenceRecord while preserving corpus provenance and original identifiers. Do not silently merge its records into Institutional corpus.

### C. Private staging research

Use only a separate service operation requiring privileged research scope. Return explicit labels:
- evidence_tier = private_staging
- publication_state = unpublished
- trusted = false unless a reviewed policy says otherwise
- user_citation_eligible = false

Never pass these rows to the standard final citation resolver. UI and final answer must state that material is provisional/internal research.

### D. Web captures and derived synthesis

Web captures, AI-derived claims, graph edges, and synthesis staging are candidates until source verification and human publication gates pass. A browser anchor or URL is not equivalent to a verified page citation. Capture time and source modification time are distinct fields.

## 4. Hybrid retrieval algorithm (target after approval)

1. Normalize query without deleting proper nouns, numbers, negation, dates, or domain-specific terms.
2. Detect language and domain; generate a small number of transparent query variants.
3. Apply caller authorization and corpus filters before candidate generation.
4. Run lexical retrieval and vector retrieval with identical evidence eligibility predicates.
5. Optionally rerank a bounded candidate set.
6. Fuse ranks with RRF inside the same corpus and policy tier:
   RRF(d) = sum_i 1 / (k + rank_i(d)).
7. Deduplicate by immutable evidence/chunk ID and source page.
8. Apply diversity limits so one source cannot dominate all results.
9. Verify source hash, locator, approval state, model attestation, and retrieval-scope flags again before returning.
10. Return provenance fields and retrieval diagnostics.

Start with k = 60 only as a baseline for evaluation; tune on a held-out dataset. Do not add arbitrary domain multipliers until they show measured improvement. If corpora are combined, preserve per-corpus rank and use a separately calibrated fusion policy.

## 5. Embedding invariants

The inspected Institutional staged hybrid function expects:
- vector dimension = 384;
- norm approximately 1 (0.98 to 1.02);
- approved model ID/artifact SHA-256 match;
- model approval status = approved;
- non-null human attestor and attestation timestamp;
- exact content hash and source hash consistency;
- embedding status VERIFIED.

Legacy semantic retrieval also enforces 384 dimensions and checks intfloat/multilingual-e5-small. Do not assume those requirements apply to every future model; define an immutable versioned embedding profile. Never compare vectors from different embedding spaces.

## 6. Citation object

Every citation binds:
- evidence_id;
- corpus_id;
- source_id;
- chunk_id;
- source_title;
- source_hash;
- locator_type;
- page_start/page_end or stable section/URL anchor;
- retrieved_at;
- retrieval_method;
- review_status;
- publication_state;
- evidence_tier.

Citation resolution is server-side. The model may reference an existing evidence handle but cannot invent one. If source hash changes since indexing, invalidate citation and require re-ingestion or revalidation.

## 7. Contradiction and temporal handling

- Preserve claims from multiple sources when they conflict.
- Record source publication date, capture time, effective date, event date, and last verified time separately.
- Prefer primary/official sources where relevant, but do not suppress credible conflicting sources.
- Distinguish latest available source from source describing latest event.
- For political/business intelligence, track actor, organization, interest, action, relationship, and validity interval, each linked to source evidence.

## 8. Retrieval evaluation

Benchmark dimensions:
- Indonesian and English queries;
- exact name/entity and alias;
- dates, amounts, percentages, and IDs;
- negation and exception conditions;
- multi-hop and cross-document questions;
- tables and page-scoped PDF excerpts;
- conflicting sources;
- stale versus current sources;
- malicious prompt-injection text inside retrieved documents;
- no-answer and unindexed-source cases.

Metrics:
- Recall@5 / Recall@10;
- MRR and nDCG@10;
- evidence precision;
- citation precision and citation recall;
- source/page locator accuracy;
- unsupported-claim rate;
- abstention precision when eligible evidence is absent.

Do not release based on a single aggregate similarity score.

# Vector Store Adapter Decision — Supabase First, Astra Optional

**Decision date:** 2026-11-03  
**Decision:** Keep Supabase pgvector as the active primary vector backend. Do not add Astra DB in the first implementation slice.

## 1. Why

The project has an existing Supabase PostgreSQL 17 project with pgvector 0.8.2, legacy vector search, and Institutional RAG retrieval/governance. The current institutional lifecycle depends on Supabase tables and RPC predicates for source hashes, evidence review, reviewer quorum, embedding model attestation, page-located excerpts, and publication.

Introducing Astra DB now would add:
- a second vector corpus and index lifecycle;
- synchronization and reconciliation requirements;
- additional credentials/network boundary;
- risk of stale or unauthorized replicas;
- more operational and cost surface;
- no demonstrated performance requirement that justifies it.

The provided architecture's separation between vector database and chat model is correct as a general pattern. For this concrete repository, Supabase is already the vector database.

## 2. Adapter interface

Application code depends on a provider-neutral interface:

- upsert(corpus, records, embedding_profile, idempotency_key)
- query(corpus, vector, filters, limit, embedding_profile)
- delete(corpus, record_ids, source_version)
- health()
- describe_index(corpus, embedding_profile)
- reconcile(source_version, expected_count)

The adapter returns candidate IDs and retrieval scores. It does not issue evidence trust decisions.

Active first implementation:
- SupabasePgVectorAdapter for legacy/approved corpus methods that are already exposed through reviewed RPCs.
- InstitutionalRagServiceAdapter for governed Institutional retrieval; do not bypass its strict retrieval RPC and query tables directly.

Optional future implementation:
- AstraDbVectorAdapter behind a separately reviewed feature flag and service credential.
- No application workflow should know provider-specific Astra API shapes.

## 3. Critical trust rule

If Astra DB is introduced, it is a candidate-search replica only, not a source-of-truth evidence service.

Candidate path:
1. Astra returns candidate source/chunk IDs and approximate relevance.
2. UGAI sends those IDs to a protected Supabase revalidation operation.
3. Supabase checks current source hash, tenant/corpus scope, review quorum, publication status, embedding attestation and citation locator.
4. Only Supabase-approved records can enter production context/citations.
5. Missing, deleted, stale, pending or revoked records are dropped and counted.

Do not use trust flags stored in Astra metadata as authorization.

## 4. Synchronization pattern if needed later

Do not synchronous dual-write from the HTTP upload request. Use:
- Supabase transaction/outbox as authoritative event;
- background projector reads durable outbox;
- idempotent upsert to external vector index;
- retry queue and dead-letter state;
- periodic reconciliation of IDs, source hashes, model profile and counts;
- tombstones for deletion/revocation;
- revalidation against Supabase on every user-facing retrieval.

Astra projection must never publish evidence or set Institutional approval flags.

## 5. Conditions that justify adding Astra DB

Consider only after:
- load testing shows Supabase vector retrieval is a bottleneck under realistic concurrency;
- query latency, index size or workload isolation requirements cannot be met through current PostgreSQL tuning;
- an evaluated alternative improves Recall@k and p95/p99 latency without reducing citation/authorization correctness;
- privacy/data residency and vendor controls are accepted;
- incremental synchronization, deletion and revalidation are proven;
- total cost and operational ownership are approved.

## 6. No dual vector spaces

Never mix embeddings from different models, versions, dimensions, normalization schemes or preprocessing pipelines. Each vector index is pinned to one immutable embedding profile. A model migration requires separate index, backfill, benchmark, shadow traffic and cutover.

## 7. Final decision

**Use Supabase pgvector now. Keep Astra DB as a future adapter, not a parallel authority.** If future requirements make Astra necessary, treat it as an explicitly synchronized retrieval projection with mandatory Supabase evidence revalidation.

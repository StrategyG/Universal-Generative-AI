# Private Notebook RAG and Tenant Isolation

**Status:** proposed data and security design; no private-notebook table or RLS policy is installed by this document.

## 1. Three distinct knowledge scopes

| Scope | Data owner | Access rule | Citation status |
|---|---|---|---|
| Institutional knowledge | Institutional RAG governance | Approved corpus policy and reviewer/publication lifecycle | Eligible only after current release gate and record eligibility pass |
| Legacy knowledge | Existing legacy RAG owner/policy | Existing legacy service authorization | Label as legacy; never upgrade to Institutional approved |
| Private notebook knowledge | User/tenant/notebook owner | Tenant membership and notebook ACL | Cite only within the caller's authorized notebook scope |

A document uploaded by a user does not automatically become institutional knowledge. A private notebook upload must not be written directly into institutional_rag.

## 2. Proposed private notebook records

Logical document record:
- document_id;
- tenant_id;
- owner_user_id;
- notebook_id;
- filename and detected_mime_type;
- original_file_sha256;
- byte_size;
- parser_version and extraction_status;
- source_created_at, source_modified_at, uploaded_at;
- retention_class and deletion_state;
- access_scope and metadata.

Logical chunk record:
- chunk_id;
- tenant_id;
- owner_user_id;
- notebook_id;
- document_id and document_version;
- chunk_index;
- content and content_sha256;
- page_start/page_end or section locator;
- token_count;
- language;
- embedding_profile_id, embedding_dimension, embedding_hash, embedding_status;
- structural metadata (heading, table, paragraph, code);
- created_at and index_version.

Use immutable document versions. Changed bytes create a new document version and new chunk IDs; do not silently replace content under old citations.

## 3. Authorization rules

- Resolve tenant_id and owner_user_id from verified authentication, not request body.
- Verify notebook membership before every search, document fetch, export, or artifact access.
- Apply document-level ACLs where sharing within a tenant is supported.
- Deny by default when membership, ownership, or scope is ambiguous.
- A notebook_id sent by the client is a requested resource identifier, not proof of access.
- Validate every returned result against the caller's current authorization at response time.
- On permission revocation, subsequent queries and citation resolution must return no access even if embeddings remain indexed.

## 4. Supabase access patterns

Preferred pattern for user-owned rows:
- user JWT context with reviewed RLS policies that enforce tenant membership and notebook access; or
- a restricted backend database role plus explicit server-side authorization and independent negative tests.

Do not assume the service_role key is protected by RLS. Supabase service-role credentials are privileged and must remain server-side. The Institutional RAG service may require service-level RPC access, but private notebook retrieval must not casually reuse a service-role query path without a separate authorization check.

Do not expose private schemas directly to anon/authenticated roles unless exact policies and function grants have been reviewed. A SECURITY DEFINER function must use a fixed safe search_path, validate caller identity, and not accept caller-supplied tenant scope as authoritative.

## 5. Query filter contract

The retrieval adapter receives an authorized scope object created by the API after authorization:
- principal_id;
- tenant_id;
- notebook_ids allowed for the current request;
- document_ids subset when user explicitly narrows scope;
- classification ceiling;
- requested time/page/language filters.

The client can request notebook/document filters, but the server intersects them with allowed scope. Empty intersection returns no accessible evidence; never fall back to global search.

Apply authorization before candidate retrieval. Do not retrieve globally and filter only after ranking because unauthorized text can leak via scores, timing, result counts, logs, or context.

## 6. Private citation semantics

A private citation includes notebook/document/chunk IDs, document version, original file hash, page/section locator, and caller-visible title. It is resolvable only by authorized notebook members.

A private notebook citation is not an Institutional RAG approval. It is a traceable source reference within a private access scope. If the document is deleted, access is revoked, or content hash changes, invalidate the citation or return a non-accessible reference according to retention policy.

## 7. Vector and lexical retrieval

Private notebook vector and lexical retrieval may use the same PostgreSQL/pgvector infrastructure but must use distinct authorization predicates. The active Institutional strict retrieval RPC is not a general private notebook query endpoint.

For private notebook retrieval:
- query vector must match the immutable embedding profile used by the target index;
- metadata filters are server-generated and applied inside the retrieval query;
- lexical and vector branches share identical tenant/notebook/document constraints;
- RRF combines ranks only within the same authorized private scope;
- reranker receives only authorized candidate excerpts;
- result IDs are revalidated before context assembly.

Do not mix embedding spaces with different model versions or dimensions.

## 8. Isolation test matrix

| Test | Required result |
|---|---|
| User A queries notebook owned by B | Zero rows |
| Tenant A requests Tenant B notebook ID | 403 or indistinguishable not-found |
| User removed from shared notebook | Access revoked immediately on next request |
| Client forges tenant_id in body | Ignored/rejected |
| Client requests unauthorized document_id inside allowed notebook list | Zero rows |
| Private notebook query returns institutional result | Only if separately requested and independently authorized |
| Institutional staging result appears in notebook citations | Rejected |
| Shared link expires | Artifact and citation access denied |
| Service-role path receives forged scope | Server-side principal/scope validation rejects |
| Delete document | Content, chunks, indexes and derived artifacts follow retention/deletion policy |

## 9. Deletion and retention

Deletion must cover original object, extracted text, chunks, embeddings, derived summaries, cache entries, and artifacts according to retention policy. Use tombstones and durable deletion jobs for external projections. Record a deletion audit event without retaining private document text. Verify completion through reconciliation.

## 10. Design invariant

**Tenant isolation is an authorization property, not a metadata-filter convention.** Metadata fields help narrow the search, but only verified identity, ACL checks, database policy, and negative tests prove that a user can access a chunk.

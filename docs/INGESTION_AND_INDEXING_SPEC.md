# Document Ingestion and Indexing Specification

**Status:** target workflow. It does not change existing Supabase ingestion jobs or source records.

## 1. Ingestion is an asynchronous, durable workflow

The API validates and creates a job; workers process documents. Never parse arbitrary large ZIP/PDF files in the request process.

Lifecycle (application-level states; map to existing DB states only after compatibility review):
RECEIVED → QUARANTINED → VALIDATING → VALIDATED → PARSING → PARSED → NORMALIZING → CHUNKING → CHUNKED → EMBEDDING → EMBEDDED → INDEXING → INDEXED → RECONCILING → RECONCILED → AI_TRIAGE → HUMAN_REVIEW_PENDING → APPROVED → PUBLISHED.

Alternative terminal/holding states: REJECTED, HOLD, FAILED, CANCELLED, EXPIRED. These are proposed workflow labels, not claimed existing Supabase enum values.

## 2. Upload and archive controls

- Enforce request byte limit before full buffering.
- Verify file signature/magic bytes; do not trust extension or client MIME.
- Allowlist formats and parser versions.
- Set maximum compressed bytes, uncompressed bytes, entry count, expansion ratio, path depth, per-entry size, page count, and processing time.
- Reject absolute paths, parent traversal, symlinks, duplicate normalized paths and unsupported nested archives.
- Reject encrypted or malformed archives unless a secure password workflow is explicitly supported.
- Store uploads in quarantine outside executable paths.
- Malware scanning and content-disarm policy should run before parser execution where supported.
- Run parsers in isolated worker/container with CPU, memory and wall-time limits.
- Treat embedded URLs, macros, prompt text and scripts as untrusted content.

## 3. Source identity and deduplication

For each uploaded object:
- compute SHA-256 over original bytes;
- record byte size, detected MIME, original filename, uploader/tenant/notebook, capture time, parser version and ingest job ID;
- generate an immutable source identifier;
- detect same-content duplicates using checksum and tenant access policy;
- do not overwrite an older source version silently;
- distinguish source_modified_at, captured_at, indexed_at, and event_date.

A same-hash duplicate may reuse parsing/index data only when ownership, permissions, retention and corpus policy allow it. Cross-tenant existence must not be disclosed.

## 4. Parsing and structural extraction

Preserve document structure:
- page boundaries and page labels;
- headings and section hierarchy;
- paragraph boundaries;
- table title, headers, rows, columns and cell coordinates when available;
- code blocks and language;
- footnotes, captions and source metadata;
- timestamps for audio/video transcript segments.

OCR is a fallback for image-only pages or extraction quality failures, not a default pass on every page. Record extraction method and confidence. Do not invent page numbers for sources without page semantics.

## 5. Semantic chunking

Chunking should respect document boundaries and semantic units:
- use token-based size constraints, not fixed character counts;
- keep headings attached to their content;
- do not split table headers from data rows;
- do not merge unrelated sections;
- retain overlap only where it improves retrieval and does not duplicate provenance;
- preserve page_start/page_end and section locator;
- retain source offsets where parser supports them.

A configurable initial chunk range such as 400–800 tokens with modest overlap can be benchmarked, but must not become a universal fixed setting. Evaluate by document type and task.

Each chunk has stable ID, source ID/hash, chunk index, exact page/section locator, text content hash, token count, parser/chunker version, language and structural metadata.

## 6. Embedding profile and model governance

An embedding profile is immutable and includes:
- model identifier and provider;
- artifact/tree SHA-256;
- output dimension;
- normalization method;
- tokenizer/preprocessing version;
- input prefix/instruction profile where applicable;
- effective date and human attestation;
- approved/revoked status.

Current inspected Institutional staged hybrid retrieval checks:
- 384 dimensions;
- vector norm approximately 0.98–1.02;
- intfloat/multilingual-e5-small;
- model artifact hash matches an approved, human-attested record;
- content and source hashes match;
- embedding status VERIFIED.

Legacy semantic retrieval also validates 384-dimensional normalized vectors and the intfloat/multilingual-e5-small model label.

Do not change embedding model or dimension in place. New embedding profile requires a separate versioned index/backfill/evaluation and controlled cutover.

## 7. Indexing

Primary project implementation:
- Supabase PostgreSQL stores authoritative source/chunk/metadata.
- pgvector stores the primary semantic representation.
- PostgreSQL full-text search provides lexical retrieval.
- Existing retrieval RPCs enforce corpus-specific eligibility.

For each chunk, indexing must be idempotent on source version + parser/chunker version + embedding profile. A retry cannot create duplicate active rows or publish a partial document.

Write sequence:
1. persist source and parser manifest;
2. persist chunk records with provenance;
3. generate embeddings under approved profile;
4. validate dimension/norm/hash;
5. write vector and lexical indexes;
6. reconcile indexed rows and counts;
7. record job completion and audit event;
8. continue to AI triage/review; do not auto-publish.

The database's current governance lifecycle must be retained. A successful indexing job is not an evidence approval.

## 8. Evidence eligibility and publication

Index state and evidence publication are independent. The ingestion system may write a chunk but must not set approved, trusted, reviewer identity, quorum, or published state based on model output.

The model may produce AI triage candidates. Human review and existing quorum/veto/publication gates remain the authority.

## 9. Ingestion acceptance tests

- oversized body and oversized archive reject before resource exhaustion;
- ZIP path traversal/symlink/zip bomb rejected;
- spoofed MIME rejected;
- repeated upload is idempotent;
- same source with changed bytes becomes a new version;
- parser preserves page/section locators;
- table extraction preserves headers and values;
- OCR fallback records method and quality;
- embedding dimension/norm/model/hash mismatch blocks index;
- partial failure does not mark document indexed;
- staging chunks cannot be returned as production citations;
- tenant A cannot enumerate, retrieve or infer tenant B documents;
- failed worker can be resumed safely using idempotency and lease fencing.

## 10. Operational telemetry

Record job ID, source hash, parser/chunker/model versions, bytes, page count, chunk count, embedding count, skipped/rejected pages, worker time, retry count, output checksum, failure code and reconciliation result. Avoid logging full private document text.

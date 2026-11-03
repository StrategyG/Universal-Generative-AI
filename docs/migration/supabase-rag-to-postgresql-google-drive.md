# Move the RAG environment from Supabase to PostgreSQL + Google Drive

## Source inventory (read-only inspection)

Source project: `institutional-rag`, PostgreSQL 17.11, region `ap-southeast-1`.

The source contains two application schemas:
- `rag`: legacy documents/chunks/ingestion state and audit events.
- `institutional_rag`: institutional documents, extracted chunks, evidence staging, reviews, synthesis, embedding jobs, evaluation data, retrieval functions and readiness views.

The source has 25 base tables containing **31,426 rows** across the two RAG schemas: 27,641 in `rag` and 3,785 in `institutional_rag`. The inspected per-table counts are:

| Schema | Table | Exact rows |
|---|---|---:|
| rag | audit_events | 1,071 |
| rag | chunks | 26,186 |
| rag | documents | 383 |
| rag | ingest_jobs | 1 |
| institutional_rag | ai_deep_reviews_v1 | 14 |
| institutional_rag | ai_evidence_reviews | 578 |
| institutional_rag | chat_review_pilot_feedback | 2 |
| institutional_rag | chat_review_pilot_items | 4 |
| institutional_rag | document_chunks | 1,109 |
| institutional_rag | embedding_jobs | 293 |
| institutional_rag | embedding_model_approvals | 0 |
| institutional_rag | evaluation_cases | 34 |
| institutional_rag | evaluation_results | 38 |
| institutional_rag | evidence_staging_index | 333 |
| institutional_rag | ingestion_runs | 4 |
| institutional_rag | knowledge_candidates | 669 |
| institutional_rag | knowledge_relations_staging | 53 |
| institutional_rag | knowledge_synthesis_members | 74 |
| institutional_rag | knowledge_synthesis_staging | 8 |
| institutional_rag | production_release_evidence | 0 |
| institutional_rag | review_votes | 0 |
| institutional_rag | reviewer_registry | 0 |
| institutional_rag | source_documents | 434 |
| institutional_rag | web_evidence_staging | 69 |
| institutional_rag | web_source_captures | 69 |

These are read-only exact counts from the inspection query, not a completed transfer or a later live snapshot. The migration runner recomputes counts from one exported PostgreSQL snapshot and verifies every target table after restore.

### Current quality blockers

- `rag.chunks`: 26,186 rows, 682 embeddings populated, 25,504 missing. Existing populated vectors are 384-dimensional.
- `institutional_rag.document_chunks`: 1,109 rows, zero embeddings populated.
- `institutional_rag.embedding_jobs`: 293 jobs; 198 blocked and 95 queued. All target `intfloat/multilingual-e5-small`, 384 dimensions.
- `institutional_rag.knowledge_candidates`: 669 candidates; 486 pending and 183 need more evidence. None are marked published. Trusted retrieval should not be considered production-ready while there are no published candidates.
- Institutional source documents: 384 Dropbox and 50 web sources. 358 Dropbox source records have valid SHA-256 values; 26 do not.
- The Supabase Storage bucket inventory is empty. Original Dropbox documents are not stored in Supabase Storage.
- RAG schemas contain 25 base tables, retrieval functions, and review/readiness views. The only user-defined table-column type is `extensions.vector`; all other columns use PostgreSQL built-in types. RAG functions do not reference `auth`, `storage`, `vault`, or `public` objects. The `rag` tables have explicit deny policies for `anon` and `authenticated`. Institutional tables have RLS enabled but no row policies; default access must remain denied to external roles. Source inspection found 21 routines and zero `SECURITY DEFINER` routines (all 21 are `SECURITY INVOKER`); the migration rechecks this and refuses runtime grants if any definer routine appears, so a superuser-owned routine cannot become an application execution path.
- Three institutional foreign keys reference `auth.users`; reviewer and attestation tables were empty at inspection time. Three readiness/reviewer views also depend on `auth.users.email_confirmed_at`. The migration runner rewrites those view dependencies to `ugai_identity.actors`, preserves the readiness checks, converts the foreign keys, and drops the temporary Auth compatibility schema. It independently checks that no additional foreign key to `auth` remains and fails closed rather than cascading an unmapped dependency away. It does not copy passwords, tokens, or user profiles. Historical actor references remain unverified until a new identity provider attests them.

Do not mark pending or unreviewed evidence as trusted or published during migration.

## Target design

- PostgreSQL 17 or newer is the system of record for RAG tables, 384-dimensional vectors, indexes, SQL retrieval functions, views, audit history, ingestion queues, reviews and metadata.
- Google Drive stores an encrypted PostgreSQL snapshot and, after the Dropbox source is connected, the original source files and evidence packages.
- A private, non-login database role `ugai_runtime` is used by the trusted backend. It is the only role given RAG schema access by the migration runner.
- `anon` and `authenticated` remain no-login and have no grants. Existing `rag.deny_api_roles` policies are retained.
- `ugai_identity.actors` replaces the Supabase Auth foreign-key dependency without copying passwords, tokens or Supabase Auth internals.

## Required dependencies

- PostgreSQL 17+ destination with `pgvector` 0.8.2+ and `pgcrypto` available.
- PostgreSQL client utilities `pg_dump` and `pg_restore` version 17+.
- A Google Cloud service-account JSON file with write access to a restricted folder inside a Google Shared Drive. Standalone service accounts cannot upload into their own My Drive storage; the uploader sends `supportsAllDrives=true` and verifies the target folder is writable.
- A 32-byte encryption key encoded as Base64.
- For original file transfer, the Dropbox connection and permission to read the original source files.

## Environment variables

Set these in a protected shell or secret store. Never put them in Git, notebooks, chat messages, or logs.

- `SOURCE_DATABASE_URL`: source Supabase PostgreSQL connection string, with `sslmode=require`.
- `TARGET_DATABASE_URL`: new PostgreSQL connection string; use `sslmode=require` for a remote target. The loopback-only local Docker target may use its local non-TLS connection.
- `GOOGLE_APPLICATION_CREDENTIALS`: path to the Google service-account JSON file.
- `GOOGLE_DRIVE_FOLDER_ID`: restricted destination folder ID.
- `UGAI_EXPORT_ENCRYPTION_KEY_B64`: Base64 of exactly 32 random bytes.

Generate a key locally:
```bash
python -c "import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

## Safe migration

Install optional dependencies:
```bash
pip install -e '.[rag-migration]'
```

First run the non-mutating preflight:
```bash
python -m ugai_decision.rag_migration
```

Only after confirming the source, destination, Drive folder and backup policy, execute:
```bash
python -m ugai_decision.rag_migration --apply
```

## Backup recovery

Download the encrypted `rag-schemas.dump.enc` object from the restricted Drive folder to a protected machine. Set the same `UGAI_EXPORT_ENCRYPTION_KEY_B64` value from the secret store; never send it in chat or commit it.

Authenticate and decrypt to a new local file:
```bash
python -m ugai_decision.rag_migration \
  --decrypt-backup /secure/path/rag-schemas.dump.enc \
  --output /secure/path/rag-schemas.dump
```

The command validates the AES-256-GCM authentication tag before reporting success and refuses to overwrite an existing output file. Restore the resulting PostgreSQL custom archive to a new empty PostgreSQL 17+ database with `pg_restore`; do not restore over the live source or an existing RAG target.

The runner:
1. Opens the source in a read-only repeatable-read transaction and exports a PostgreSQL snapshot.
2. Checks both server versions, extensions, distinct database identity and empty destination schemas.
3. Uses `pg_dump` custom format to capture both RAG schemas, data, constraints, indexes, functions, views and RLS policies using the same exported snapshot.
4. Encrypts the dump with streaming AES-256-GCM before uploading it to Google Drive.
5. Creates required extensions and inert roles in the target, restores the archive in one transaction, then replaces the temporary Auth compatibility schema with `ugai_identity.actors`.
6. Applies private backend grants and role-specific RLS policies. API-facing roles remain denied.
7. Compares every table's exact source and target row counts. Any mismatch fails the migration.

The source is never modified. The destination is never dropped or overwritten; the runner requires a dedicated target database without `rag`, `institutional_rag`, or a pre-existing `auth` schema. The encrypted Drive backup is uploaded before restore. After migration, create a non-public application login and grant it membership in `ugai_runtime`; do not give the application role ownership, superuser, or `BYPASSRLS` privileges.

## Remaining cutover work

This database migration does not download Dropbox files. Source file records currently refer to Dropbox and the Supabase Storage bucket list is empty. Once Dropbox access is connected, download each source using its provider ID/path, verify the original SHA-256 where present, upload to the restricted Drive folder, and write the resulting Drive file ID and checksum into a companion file registry. Missing hashes must be re-hashed from the original file; do not trust old metadata.

After database restore:
- Re-embed the 25,504 legacy chunks missing vectors only after confirming their content and source hashes.
- Re-embed the 1,109 institutional chunks under the approved 384-dimensional model artifact; the current model approval table is empty, so the approval attestation gate must be completed before any job is submitted.
- Reconcile 198 blocked and 95 queued jobs; do not silently reset blocked jobs.
- Preserve all 669 knowledge candidates as pending/needs-more-evidence; maintain two-reviewer and source-provenance gates.
- Run lexical, semantic and hybrid retrieval regression tests against a fixed evaluation set and compare citation/source/page correctness.
- Test backup restore, Drive checksum verification, role denial, audit append-only behavior and application health.
- Only then cut over traffic. Keep Supabase untouched until a signed acceptance and rollback window are complete. Add a policy and grant review to every future schema migration; newly created RLS tables must receive an explicit runtime policy.

## Cutover status

This repository change provides the migration runner and security contract. It does not claim a completed data migration: live database URLs, destination credentials, Google service-account access and Dropbox connection must be configured by the operator. The Supabase source remains the rollback copy.

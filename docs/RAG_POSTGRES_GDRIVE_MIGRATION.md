# RAG migration: PostgreSQL primary + encrypted Google Drive backup

## Target architecture

- PostgreSQL is the operational database for RAG, provenance, embeddings, workflow state and decision audit.
- Google Drive is an encrypted off-site archive for database backup artifacts and manifests.
- IM19 remains the only outbound MCP gateway; provider credentials stay in its secret boundary.
- UGAI uses generic PostgreSQL pools and injected ports. There is no Supabase/PostgREST runtime dependency.

The former Supabase project is a **legacy source** during migration only. It must not be paused or deleted until the encrypted Drive archive exists, the target restore passes row-count validation, application retrieval passes acceptance tests, and a final backup is retained.

## Source inventory observed

Read-only inspection of the existing source project found:
- `rag.documents`: 383 rows.
- `rag.chunks`: 26,186 rows, including the 384-dimensional vector embeddings.
- `rag.ingest_jobs`: 1 row.
- `rag.audit_events`: 1,071 rows.
- Additional RAG governance/evidence tables in `institutional_rag`: source documents, page-aware chunks, embedding jobs, model approvals, review votes, evidence staging, AI reviews, web captures and knowledge synthesis.

Installed source extensions included `vector` 0.8.2, `pgcrypto` 1.3 and `uuid-ossp` 1.1. The migration preserves the `rag` and `institutional_rag` schemas and recreates these PostgreSQL extensions on the destination. Exact row counts for every table are read at runtime and compared after restore; the figures above are an initial inventory, not the final migration manifest.

## Backup and restore utility

The utility uses PostgreSQL-native `pg_dump` custom archives and `pg_restore`. It:
1. Reads all ordinary tables in both schemas and records exact source row counts.
2. Exports schema definitions, data, stored procedures, indexes, constraints, RLS policies and vector values.
3. Encrypts the dump with `age` before uploading to Google Drive.
4. Uploads the encrypted archive to the configured Drive folder using a service account.
5. Restores to an empty, separate PostgreSQL database after checking the PostgreSQL version and required extensions.
6. Revokes default PUBLIC access and validates every table's row count on the target.
7. Uploads a JSON manifest containing archive SHA-256, extension versions, table counts, Drive file ID and restore status.

No source prompts, provider credentials, service-role keys, OAuth refresh tokens or database passwords are written to GitHub. Database passwords are passed to PostgreSQL tools through temporary permission-restricted `.pgpass` files, not command-line arguments. Plaintext dumps and temporary credentials are deleted when the process exits.

### Prerequisites

- PostgreSQL 17 or later client binaries: `pg_dump`, `pg_restore`, `psql`.
- `age` command-line utility and an X25519 recipient key. Keep its private identity key offline.
- A destination PostgreSQL 17+ database with the `vector`, `pgcrypto` and `uuid-ossp` extensions available.
- A Google Cloud service account JSON credential with access to the destination Drive folder. Share that folder with the service-account email.
- Install the optional dependencies: `pip install -e ".[rag-migration]"`.

### Required environment variables

```dotenv
SOURCE_DATABASE_URL=postgresql://...
TARGET_DATABASE_URL=postgresql://...
GOOGLE_APPLICATION_CREDENTIALS=/secure/path/drive-service-account.json
GOOGLE_DRIVE_FOLDER_ID=<folder-id>
RAG_BACKUP_AGE_RECIPIENT=age1...
```

Use a source connection with read access to all rows and RAG objects. Use a target database administrator capable of creating the two policy roles and required extensions. Never commit these values to a repository or notebook.

### Run

```bash
python scripts/migrate_rag_to_postgres_drive.py
```

The target must be a separate, empty database. The utility refuses to restore over existing tables in either RAG schema and never drops or truncates source data. It requires source and target to be different databases.

The dump includes only `rag` and `institutional_rag`; it intentionally excludes Supabase-managed `auth`, `storage`, `vault`, realtime and platform control schemas. Application authentication and object-storage migration are separate workstreams and are not represented as completed here.

## Runtime cutover

1. Run the migration in an isolated environment with source/target credentials and Drive access.
2. Verify the Drive archive and manifest SHA-256 values; keep the age private key in a separate secure location.
3. Verify source and destination exact row counts, extension availability, search functions, vector dimension (384), and representative lexical/hybrid retrieval results.
4. Configure least-privilege login roles for UGAI RAG reader, ingestion worker, review/promotion service and workflow runtime. Do not connect application processes as the database owner.
5. Switch UGAI to `DATABASE_URL` / asyncpg and inject `PostgresDecisionAuditSink` into `DecisionWorkflow`.
6. Run concurrency, RLS/role, ingestion, evidence quorum, approval, backup-restore and recovery acceptance tests.
7. Remove Supabase environment variables and deployment dependencies only after all runtime paths pass.

The archive script revokes PUBLIC access after restore; application-specific roles must be granted the minimum privileges required by the approved runtime design before enabling traffic.

## Google Drive connector limitation

The ChatGPT Google Drive connector is currently disabled by administrator policy in this environment. The repository utility therefore uploads from the trusted deployment/backup runner using Google service-account credentials; it does not claim that a Drive upload has already happened from this chat session.

## Decommission gate

Do not pause or delete the source project yet. Decommission is permitted only after:
- the encrypted archive and manifest are present in Drive and independently checksum-verified;
- all table counts match and vector/search tests pass against the target;
- UGAI and IM19 runtime tests pass with PostgreSQL as the only database;
- a second backup/restore drill succeeds; and
- the owner explicitly confirms the irreversible decommission action.

Until then, keep the former source project read-only and retain its backups.

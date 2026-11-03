# Google Drive + PostgreSQL architecture

## Provider replacement

This design replaces the Supabase-specific audit persistence adapter with standalone PostgreSQL and Google Drive adapters. It does not change the decision engine or workflow ports.

- PostgreSQL is the operational source of truth for audit events and evidence metadata.
- Google Drive stores source files and evidence packages in a restricted folder.
- PostgreSQL records the Drive file ID, SHA-256, file size, MIME type, actor, and provenance.
- UGAI continues to enforce trusted actor identity, evidence provenance, human approval, plan-digest binding, and idempotent execution.
- MCP remains a transport for evidence/tool access; it is not the audit database.

## Data flow

1. An authenticated evidence source supplies document bytes and provenance.
2. The Drive adapter computes SHA-256 and uploads bytes to a configured folder.
3. The registry records Drive identity and checksum in PostgreSQL.
4. The workflow appends decision events to PostgreSQL.
5. Approval and execution remain fail-closed and bound to actor, decision, plan digest, and idempotency key.

## Security

- Inject a Drive API v3 client created by the host application; this package never creates credentials.
- Use the narrowest feasible OAuth scope or a service account with access only to a dedicated Shared Drive/folder.
- Store credentials and database URLs in a secret manager, never in Git.
- Use TLS and a dedicated non-owner PostgreSQL role.
- Keep Drive folder membership restricted; a Drive URL is not authorization.
- The migration blocks UPDATE and DELETE on audit events. Do not grant TRUNCATE or table ownership to the runtime role.
- Database owners remain privileged. For stronger tamper evidence, sign periodic audit checkpoints and store them in an independently administered immutable archive.

## Setup

Install optional dependencies:
    pip install asyncpg google-api-python-client

Apply the standalone PostgreSQL migration:
    psql "$UGAI_DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/postgresql/001_create_ugai_audit.sql

Create an asyncpg pool and inject it into PostgresDecisionAuditSink and PostgresEvidenceRegistry. Construct an authenticated Google Drive API v3 service outside this package and inject it into GoogleDriveEvidenceArchive.

## Not yet production-connected

This change adds adapters and schema only. It does not provision a PostgreSQL host, Google Cloud project, OAuth credentials, or production Drive folder; it does not migrate live Supabase records or switch production traffic. Those require credentials, a tested backfill, reconciliation, rollback plan, and explicit cutover approval.

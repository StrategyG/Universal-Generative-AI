# Local PostgreSQL environment for the RAG migration

This creates a dedicated PostgreSQL 17 + pgvector target on the operator's machine. It does not create a cloud resource and does not change the Supabase source project.

## Requirements

- Docker Engine/Desktop with the Compose plugin.
- At least 4 GB RAM available to Docker; 8 GB is preferable for the 31k-row source snapshot and index restoration.
- Sufficient free disk space for the restored database and temporary archive. The encrypted backup is separately stored in Google Drive during the migration.

## Initialize

From the repository root:

```bash
cp .env.example .env
```

Generate a unique password locally. Example on Linux/macOS:

```bash
openssl rand -hex 32
```

Put the generated value in `POSTGRES_PASSWORD` and use the same value in `TARGET_DATABASE_URL`. Keep the password URL-safe; the hex output above is URL-safe. Do not commit `.env`. Leave the source and Google Drive migration settings empty until their credentials and folder are prepared. Generate the independent archive key with `openssl rand -base64 32` and store it in `UGAI_EXPORT_ENCRYPTION_KEY_B64` only in the local ignored `.env` file or a secret manager.

Start PostgreSQL:

```bash
docker compose up -d
docker compose ps
docker compose logs --tail=100 postgres
```

The service binds only to `127.0.0.1:55432`; it is not exposed to the public network. Persistent database files live in the named Docker volume `ugai_rag_pgdata`.

## Verify the empty target

```bash
docker compose exec postgres pg_isready -U ugai_admin -d ugai_rag
docker compose exec postgres psql -U ugai_admin -d ugai_rag -c "SELECT version();"
docker compose exec postgres psql -U ugai_admin -d ugai_rag -c "SELECT name, default_version FROM pg_available_extensions WHERE name IN ('vector','pgcrypto');"
```

Expected: PostgreSQL major version 17 and both `vector` and `pgcrypto` listed as available. The migration runner creates the extensions and application schemas after the source snapshot has been safely archived.

## Configure migration process

Install the migration dependencies and PostgreSQL 17 client utilities (`pg_dump`, `pg_restore`) on the host running the migration:

```bash
python -m pip install -e ".[rag-migration]"
pg_dump --version
pg_restore --version
```

Load the protected local variables into the shell running the migration:
```bash
set -a
. ./.env
set +a
```

Also provide `SOURCE_DATABASE_URL` from the Supabase database connection settings with `sslmode=require` (or stronger, such as `verify-full`), `GOOGLE_DRIVE_FOLDER_ID`, `UGAI_EXPORT_ENCRYPTION_KEY_B64` (a securely generated 32-byte key encoded as Base64), and the Google service-account credential path in `GOOGLE_APPLICATION_CREDENTIALS`. The destination **must be a restricted folder inside a Google Shared Drive**: standalone service accounts have no personal Drive storage quota and cannot own files in My Drive. Add the service-account email to the Shared Drive with at least **Contributor** access (API role `writer`). Do not make the folder public and do not paste or commit any secret.

Verify the Drive destination before connecting the database or creating a dump:

```bash
python -m ugai_decision.rag_migration --check-drive
```

Expected: `state: drive_destination_ready`, a Shared Drive ID, and a folder ID. The command fails closed if the folder is not in a Shared Drive or the service account cannot add children to it.

Run the non-destructive database preflight next:

```bash
python -m ugai_decision.rag_migration
```

The preflight reads source and target metadata and row counts but does not write to either database. The target must be empty and dedicated; never point it at an existing database containing application schemas.

Only after the preflight matches the intended source and target, the Google Drive folder and backup key have been tested, and the operator explicitly approves the cutover, run the documented `--apply` command. This setup guide does not authorize that operation.

## Create a least-privilege application login

The migration administrator account is for provisioning only. The restored RAG objects are granted to the private `ugai_runtime` role, which is intentionally `NOLOGIN`. After a successful restore, create a separate application login and grant membership; never connect the application as `ugai_admin`:

```sql
CREATE ROLE ugai_app LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT CONNECT ON DATABASE ugai_rag TO ugai_app;
GRANT ugai_runtime TO ugai_app;
\\password ugai_app
```

Run this from an administrator `psql` session. The `\\password` command prompts without placing the password in shell history. Configure the application with the new login and a TLS-protected connection in production. Do not grant `ugai_app` superuser, table ownership, or `BYPASSRLS`.

## Stop and retain data

```bash
docker compose stop
```

Do not run `docker compose down -v`: the `-v` flag deletes the persistent PostgreSQL volume.

## Security boundaries

- Host port is loopback-only.
- Password authentication uses SCRAM-SHA-256.
- No password, service-account JSON, encryption key, dump, or database volume is committed.
- Supabase remains the authoritative source until exact per-table row-count checks and application-level retrieval/evaluation tests pass.
- Local Docker is suitable for development and migration rehearsal, not a highly available production database. Production requires managed/self-hosted operations, encrypted off-device backups, monitoring, patching, restore drills and network/identity controls.

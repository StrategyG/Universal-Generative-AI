"""Safe, encrypted Supabase RAG export and standalone PostgreSQL import.

The source is read-only. The destination must be empty for the two RAG schemas.
The dump is encrypted before it is archived to a restricted Google Drive folder.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path


SCHEMAS = ("rag", "institutional_rag")
REQUIRED_EXTENSIONS = {"vector": "0.8.2", "pgcrypto": "1.3"}
ACTOR_FK_MIGRATIONS = (
    ("institutional_rag.reviewer_registry", "reviewer_registry_reviewer_id_fkey", "reviewer_id"),
    ("institutional_rag.embedding_model_approvals", "embedding_model_approvals_attested_by_fkey", "attested_by"),
    ("institutional_rag.production_release_evidence", "production_release_evidence_attested_by_fkey", "attested_by"),
)
ENCRYPTED_MAGIC = b"UGAI-DB-DUMP-AES256GCM-v1"


class MigrationError(RuntimeError):
    """Raised when a migration precondition or verification fails."""


def _pgpass_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(":", "\\:")


def _dsn_parts(dsn: str) -> dict[str, str]:
    if not dsn or not dsn.startswith(("postgres://", "postgresql://")):
        raise MigrationError("Database DSNs must use postgres:// or postgresql://")
    from psycopg.conninfo import conninfo_to_dict

    return conninfo_to_dict(dsn)


def _safe_dsn_and_pgpass(dsn: str) -> tuple[str, str | None]:
    """Return a password-free DSN and an optional .pgpass record."""
    from psycopg.conninfo import make_conninfo

    parts = _dsn_parts(dsn)
    password = parts.pop("password", None)
    pgpass_record = None
    if password:
        host = parts.get("host") or "localhost"
        port = parts.get("port") or "5432"
        database = parts.get("dbname") or "*"
        user = parts.get("user") or "*"
        pgpass_record = ":".join(
            _pgpass_escape(item) for item in (host, port, database, user, password)
        )
    return make_conninfo(**parts), pgpass_record


def _validate_encryption_key(encoded: str) -> bytes:
    try:
        key = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise MigrationError("UGAI_EXPORT_ENCRYPTION_KEY_B64 must be valid Base64") from exc
    if len(key) != 32:
        raise MigrationError("UGAI_EXPORT_ENCRYPTION_KEY_B64 must decode to exactly 32 bytes")
    return key


def _encrypt_dump(source: Path, destination: Path, key: bytes) -> str:
    """Stream-encrypt a dump without loading the complete dump into memory."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    nonce = os.urandom(12)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(ENCRYPTED_MAGIC)
    digest = hashlib.sha256()
    with source.open("rb") as reader, destination.open("wb") as writer:
        writer.write(ENCRYPTED_MAGIC)
        writer.write(nonce)
        while block := reader.read(1024 * 1024):
            encrypted = encryptor.update(block)
            writer.write(encrypted)
            digest.update(encrypted)
        writer.write(encryptor.finalize())
        writer.write(encryptor.tag)
    return digest.hexdigest()


def _run(command: list[str], *, env: dict[str, str]) -> None:
    try:
        subprocess.run(command, check=True, env=env, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise MigrationError(f"Required PostgreSQL utility not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        # Do not echo command arguments: they can contain host/user/database details.
        message = (exc.stderr or exc.stdout or "unknown PostgreSQL utility error")[-5000:]
        raise MigrationError(f"{command[0]} failed: {message}") from exc


def _major_version(version_text: str) -> int:
    match = re.search(r"\b(\d+)(?:\.\d+)?", version_text)
    if not match:
        raise MigrationError(f"Could not parse PostgreSQL utility version: {version_text}")
    return int(match.group(1))


def _connect(dsn: str):
    import psycopg

    return psycopg.connect(dsn, autocommit=False)


def _schema_counts(connection) -> dict[str, int]:
    from psycopg import sql

    objects = connection.execute(
        """
        SELECT n.nspname, c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname = ANY(%s) AND c.relkind IN ('r','p')
        ORDER BY n.nspname,c.relname
        """,
        (list(SCHEMAS),),
    ).fetchall()
    counts: dict[str, int] = {}
    for schema_name, table_name in objects:
        count = connection.execute(
            sql.SQL("SELECT count(*) FROM {}.{}").format(
                sql.Identifier(schema_name), sql.Identifier(table_name)
            )
        ).fetchone()[0]
        counts[f"{schema_name}.{table_name}"] = int(count)
    return counts


def _extension_inventory(connection) -> list[dict[str, str]]:
    rows = connection.execute(
        """
        SELECT e.extname,e.extversion,n.nspname
        FROM pg_extension e
        JOIN pg_namespace n ON n.oid=e.extnamespace
        WHERE e.extname IN ('vector','pgcrypto','uuid-ossp')
        ORDER BY e.extname
        """
    ).fetchall()
    return [
        {"name": str(name), "version": str(version), "schema": str(schema)}
        for name, version, schema in rows
    ]


def _server_version(connection) -> int:
    return int(connection.execute("SHOW server_version_num").fetchone()[0])


def _target_preflight(connection) -> None:
    present = connection.execute(
        "SELECT nspname FROM pg_namespace WHERE nspname = ANY(%s)",
        (list(SCHEMAS),),
    ).fetchall()
    if present:
        names = ", ".join(sorted(row[0] for row in present))
        raise MigrationError(
            f"Destination already contains RAG schema(s): {names}. "
            "Use a new empty PostgreSQL database; automatic overwrite is disabled."
        )
    if connection.execute(
        "SELECT 1 FROM pg_namespace WHERE nspname='auth'"
    ).fetchone():
        raise MigrationError(
            "Destination already has an auth schema. Use a dedicated empty PostgreSQL database."
        )
    available = {
        name: version
        for name, version in connection.execute(
            "SELECT name,default_version FROM pg_available_extensions WHERE name = ANY(%s)",
            (list(REQUIRED_EXTENSIONS),),
        ).fetchall()
    }
    for extension, minimum in REQUIRED_EXTENSIONS.items():
        if extension not in available:
            raise MigrationError(f"Destination does not provide required extension: {extension}")
        if tuple(int(part) for part in available[extension].split(".")[:2]) < tuple(
            int(part) for part in minimum.split(".")[:2]
        ):
            raise MigrationError(
                f"Destination {extension} version {available[extension]} is older than {minimum}"
            )
    wrong_schema_extensions = connection.execute(
        """
        SELECT e.extname,n.nspname
        FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace
        WHERE e.extname IN ('vector','pgcrypto','uuid-ossp') AND n.nspname <> 'extensions'
        """
    ).fetchall()
    if wrong_schema_extensions:
        raise MigrationError(
            "Existing vector/pgcrypto extension must be installed in schema extensions: "
            + ", ".join(f"{name}@{schema}" for name, schema in wrong_schema_extensions)
        )
    dangerous_roles = connection.execute(
        """
        SELECT rolname FROM pg_roles
        WHERE rolname = ANY(%s) AND (rolcanlogin OR rolsuper OR rolbypassrls)
        """,
        (["anon", "authenticated", "service_role", "ugai_runtime"],),
    ).fetchall()
    if dangerous_roles:
        raise MigrationError(
            "Destination has login-enabled reserved role(s): "
            + ", ".join(row[0] for row in dangerous_roles)
        )


def _write_bootstrap(connection, source_extensions: list[dict[str, str]]) -> None:
    """Create extensions and inert compatibility roles before restoring RAG objects."""
    extension_names = {item["name"] for item in source_extensions}
    connection.execute("CREATE SCHEMA IF NOT EXISTS extensions")
    connection.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions")
    connection.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions")
    if "uuid-ossp" in extension_names:
        connection.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA extensions')
    connection.execute(
        """
        DO $roles$
        DECLARE role_name text;
        BEGIN
          FOREACH role_name IN ARRAY ARRAY['anon','authenticated','service_role','ugai_runtime']
          LOOP
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=role_name) THEN
              EXECUTE format('CREATE ROLE %I NOLOGIN', role_name);
            END IF;
          END LOOP;
        END
        $roles$
        """
    )
    # A temporary ID-only shim allows the three empty Supabase Auth foreign keys
    # to restore. It is replaced by ugai_identity.actors after the RAG restore.
    connection.execute("CREATE SCHEMA IF NOT EXISTS auth")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS auth.users (id uuid PRIMARY KEY)"
    )
    connection.commit()


def _migrate_identity_references(connection) -> None:
    connection.execute("CREATE SCHEMA IF NOT EXISTS ugai_identity")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ugai_identity.actors (
          id uuid PRIMARY KEY,
          actor_kind text NOT NULL DEFAULT 'human_or_service_actor',
          active boolean NOT NULL DEFAULT true,
          created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    for table, constraint, column in ACTOR_FK_MIGRATIONS:
        schema, relation = table.split(".", 1)
        connection.execute(
            f"""
            INSERT INTO ugai_identity.actors(id,actor_kind)
            SELECT DISTINCT {column},%s FROM {schema}.{relation}
            WHERE {column} IS NOT NULL
            ON CONFLICT (id) DO NOTHING
            """,
            (relation,),
        )
        connection.execute(
            f'ALTER TABLE {schema}.{relation} DROP CONSTRAINT IF EXISTS "{constraint}"'
        )
        connection.execute(
            f"""
            ALTER TABLE {schema}.{relation}
            ADD CONSTRAINT "{constraint}"
            FOREIGN KEY ({column}) REFERENCES ugai_identity.actors(id) ON DELETE RESTRICT
            """
        )
    connection.execute("DROP SCHEMA IF EXISTS auth CASCADE")
    connection.commit()


def _secure_runtime_access(connection) -> None:
    """Give only the non-login backend role access; public API roles remain denied."""
    connection.execute("GRANT USAGE ON SCHEMA rag,institutional_rag,extensions,ugai_identity TO ugai_runtime")
    connection.execute(
        """
        DO $secure$
        DECLARE item record;
        BEGIN
          FOR item IN
            SELECT n.nspname AS schema_name,c.relname AS table_name,c.relkind
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname = ANY(ARRAY['rag','institutional_rag'])
              AND c.relkind IN ('r','p','v','m')
          LOOP
            IF item.relkind IN ('v','m') THEN
              IF item.relkind='v' THEN
                EXECUTE format('ALTER VIEW %I.%I SET (security_invoker=true)',
                               item.schema_name,item.table_name);
              END IF;
              EXECUTE format('GRANT SELECT ON %I.%I TO ugai_runtime',
                             item.schema_name,item.table_name);
            ELSE
              EXECUTE format('GRANT SELECT,INSERT,UPDATE ON %I.%I TO ugai_runtime',
                             item.schema_name,item.table_name);
              IF item.schema_name='rag' AND item.table_name='audit_events' THEN
                EXECUTE format('REVOKE UPDATE ON %I.%I FROM ugai_runtime',
                               item.schema_name,item.table_name);
              END IF;
              IF EXISTS (
                SELECT 1 FROM pg_class t
                JOIN pg_namespace ns ON ns.oid=t.relnamespace
                WHERE ns.nspname=item.schema_name AND t.relname=item.table_name
                  AND t.relrowsecurity
              ) THEN
                EXECUTE format(
                  'DROP POLICY IF EXISTS ugai_backend_runtime ON %I.%I',
                  item.schema_name,item.table_name
                );
                EXECUTE format(
                  'CREATE POLICY ugai_backend_runtime ON %I.%I FOR ALL TO ugai_runtime USING (true) WITH CHECK (true)',
                  item.schema_name,item.table_name
                );
              END IF;
            END IF;
          END LOOP;
        END
        $secure$
        """
    )
    connection.execute(
        "GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA rag,institutional_rag TO ugai_runtime"
    )
    connection.execute(
        "REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA rag,institutional_rag FROM PUBLIC,anon,authenticated"
    )
    connection.execute(
        "GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA rag,institutional_rag TO ugai_runtime"
    )
    connection.execute(
        "REVOKE ALL ON SCHEMA rag,institutional_rag FROM PUBLIC,anon,authenticated"
    )
    connection.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA rag,institutional_rag "
        "GRANT SELECT,INSERT,UPDATE ON TABLES TO ugai_runtime"
    )
    connection.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA rag,institutional_rag "
        "GRANT EXECUTE ON FUNCTIONS TO ugai_runtime"
    )
    connection.commit()


def _drive_archive(encrypted_dump: Path, manifest_path: Path, folder_id: str) -> dict[str, str]:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not credentials_path:
        raise MigrationError("GOOGLE_APPLICATION_CREDENTIALS is required for Drive archival")
    credentials = service_account.Credentials.from_service_account_file(
        credentials_path,
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )
    service = build("drive", "v3", credentials=credentials, cache_discovery=False)

    def upload(path: Path, mime_type: str) -> str:
        request = service.files().create(
            body={
                "name": path.name,
                "mimeType": mime_type,
                "parents": [folder_id],
                "description": "UGAI encrypted Supabase RAG migration snapshot",
            },
            media_body=MediaFileUpload(
                str(path), mimetype=mime_type, resumable=True, chunksize=8 * 1024 * 1024
            ),
            fields="id,name,webViewLink",
        )
        response = None
        while response is None:
            _, response = request.next_chunk()
        return str(response["id"])

    return {
        "encrypted_dump_file_id": upload(encrypted_dump, "application/octet-stream"),
        "manifest_file_id": upload(manifest_path, "application/json"),
    }


def run_migration(*, apply: bool) -> dict[str, Any]:
    source_dsn = os.environ.get("SOURCE_DATABASE_URL", "")
    target_dsn = os.environ.get("TARGET_DATABASE_URL", "")
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")
    if not source_dsn or not target_dsn:
        raise MigrationError("SOURCE_DATABASE_URL and TARGET_DATABASE_URL are required")
    if apply and not folder_id:
        raise MigrationError("GOOGLE_DRIVE_FOLDER_ID is required for --apply")
    key = _validate_encryption_key(os.environ.get("UGAI_EXPORT_ENCRYPTION_KEY_B64", "")) if apply else None

    source_safe, source_pgpass = _safe_dsn_and_pgpass(source_dsn)
    target_safe, target_pgpass = _safe_dsn_and_pgpass(target_dsn)
    if source_safe == target_safe:
        raise MigrationError("Source and destination database DSNs must be different")

    with tempfile.TemporaryDirectory(prefix="ugai-rag-migration-") as temp_name:
        temp = Path(temp_name)
        dump_path = temp / "rag-schemas.dump"
        encrypted_path = temp / "rag-schemas.dump.enc"
        manifest_path = temp / "manifest.json"
        pgpass_path = temp / "pgpass"
        pgpass_lines = [line for line in (source_pgpass, target_pgpass) if line]
        env = os.environ.copy()
        if pgpass_lines:
            pgpass_path.write_text("\n".join(pgpass_lines) + "\n", encoding="utf-8")
            os.chmod(pgpass_path, 0o600)
            env["PGPASSFILE"] = str(pgpass_path)

        pg_dump_version = subprocess.run(
            ["pg_dump", "--version"], check=True, capture_output=True, text=True
        ).stdout
        pg_restore_version = subprocess.run(
            ["pg_restore", "--version"], check=True, capture_output=True, text=True
        ).stdout
        if _major_version(pg_dump_version) < 17 or _major_version(pg_restore_version) < 17:
            raise MigrationError("pg_dump and pg_restore version 17 or newer are required")

        with _connect(source_dsn) as source, _connect(target_dsn) as target:
            source_version = _server_version(source)
            target_version = _server_version(target)
            if source_version < 170000 or target_version < 170000:
                raise MigrationError("Source and destination PostgreSQL must both be version 17 or newer")
            source_db = source.execute(
                "SELECT current_database(),COALESCE(inet_server_addr()::text,'local')"
            ).fetchone()
            target_db = target.execute(
                "SELECT current_database(),COALESCE(inet_server_addr()::text,'local')"
            ).fetchone()
            if source_db == target_db:
                raise MigrationError("Source and destination resolve to the same database")
            _target_preflight(target)

            source.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            snapshot_id = source.execute("SELECT pg_export_snapshot()").fetchone()[0]
            counts = _schema_counts(source)
            extensions = _extension_inventory(source)
            extension_map = {item["name"]: item for item in extensions}
            for extension, minimum in REQUIRED_EXTENSIONS.items():
                if extension not in extension_map:
                    raise MigrationError(f"Source is missing required extension: {extension}")
            manifest: dict[str, Any] = {
                "snapshot_id": str(uuid.uuid4()),
                "created_at": datetime.now(UTC).isoformat(),
                "source_postgresql_major": source_version // 10000,
                "schemas": list(SCHEMAS),
                "table_row_counts": counts,
                "extensions": extensions,
                "source_project": "institutional-rag",
                "dump_format": "pg_dump custom archive",
                "archive_encryption": "AES-256-GCM",
                "migration_state": "snapshot_created",
            }

            if not apply:
                return {
                    "mode": "dry-run",
                    "source_database": source_db[0],
                    "target_database": target_db[0],
                    "table_count": len(counts),
                    "row_count": sum(counts.values()),
                    "table_row_counts": counts,
                    "extensions": extensions,
                    "snapshot_ready": bool(snapshot_id),
                }

            _run(
                [
                    "pg_dump",
                    "--format=custom",
                    "--compress=6",
                    "--no-owner",
                    "--no-privileges",
                    "--schema=rag",
                    "--schema=institutional_rag",
                    f"--snapshot={snapshot_id}",
                    f"--file={dump_path}",
                    source_safe,
                ],
                env=env,
            )
            # Release the long-lived exported source snapshot as soon as the dump is complete.
            source.commit()
            assert key is not None
            encrypted_sha256 = _encrypt_dump(dump_path, encrypted_path, key)
            manifest["encrypted_dump_sha256"] = encrypted_sha256
            manifest["encrypted_dump_size_bytes"] = encrypted_path.stat().st_size
            manifest["dump_size_bytes"] = dump_path.stat().st_size
            manifest["migration_state"] = "encrypted_snapshot_archived_pending_restore"
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
            archive_ids = _drive_archive(encrypted_path, manifest_path, folder_id)

            _write_bootstrap(target, extensions)
            _run(
                [
                    "pg_restore",
                    "--exit-on-error",
                    "--single-transaction",
                    "--no-owner",
                    "--no-privileges",
                    f"--dbname={target_safe}",
                    str(dump_path),
                ],
                env=env,
            )
            _migrate_identity_references(target)
            _secure_runtime_access(target)

            target_counts = _schema_counts(target)
            if target_counts != counts:
                missing = {
                    table: {"source": counts.get(table), "target": target_counts.get(table)}
                    for table in sorted(set(counts) | set(target_counts))
                    if counts.get(table) != target_counts.get(table)
                }
                raise MigrationError(
                    "Row-count verification failed after restore: "
                    + json.dumps(missing, sort_keys=True)
                )
            target_extensions = _extension_inventory(target)
            target_extension_map = {item["name"]: item for item in target_extensions}
            for extension, minimum in REQUIRED_EXTENSIONS.items():
                installed = target_extension_map.get(extension)
                if installed is None:
                    raise MigrationError(f"Destination extension is missing after restore: {extension}")
                if tuple(int(part) for part in installed["version"].split(".")[:2]) < tuple(
                    int(part) for part in minimum.split(".")[:2]
                ):
                    raise MigrationError(
                        f"Destination {extension} version {installed['version']} is older than {minimum}"
                    )

            manifest["migration_state"] = "restored_and_row_count_verified"
            manifest["target_postgresql_major"] = target_version // 10000
            manifest["verified_table_row_counts"] = target_counts
            manifest["drive_archive"] = archive_ids
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
            verified_manifest_id = _drive_archive_manifest_only(
                manifest_path, folder_id, env
            )
            return {
                "mode": "apply",
                "state": manifest["migration_state"],
                "table_count": len(target_counts),
                "row_count": sum(target_counts.values()),
                "drive_archive": archive_ids,
                "verified_manifest_file_id": verified_manifest_id,
                "table_row_counts": target_counts,
            }


def _drive_archive_manifest_only(manifest_path: Path, folder_id: str, _env: dict[str, str]) -> str:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    credentials = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"],
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )
    service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    request = service.files().create(
        body={
            "name": manifest_path.name.replace(".json", ".verified.json"),
            "mimeType": "application/json",
            "parents": [folder_id],
            "description": "UGAI verified PostgreSQL migration manifest",
        },
        media_body=MediaFileUpload(str(manifest_path), mimetype="application/json", resumable=True),
        fields="id",
    )
    response = None
    while response is None:
        _, response = request.next_chunk()
    return str(response["id"])


def main() -> int:
    try:
        import psycopg
    except ImportError:
        print("Install the optional dependency group: pip install -e '.[rag-migration]'", file=__import__("sys").stderr)
        return 2
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="Create an encrypted Google Drive snapshot and restore to a new empty PostgreSQL database",
    )
    args = parser.parse_args()
    try:
        result = run_migration(apply=args.apply)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (MigrationError, psycopg.Error, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"RAG migration failed: {exc}", file=__import__("sys").stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Safe, encrypted export of the Supabase RAG schemas into standalone PostgreSQL."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

SCHEMAS = ("rag", "institutional_rag")
REQUIRED_EXTENSIONS = {"vector": "0.8.2", "pgcrypto": "1.3"}
ACTOR_FKS = (
    ("institutional_rag.reviewer_registry", "reviewer_registry_reviewer_id_fkey", "reviewer_id"),
    ("institutional_rag.embedding_model_approvals", "embedding_model_approvals_attested_by_fkey", "attested_by"),
    ("institutional_rag.production_release_evidence", "production_release_evidence_attested_by_fkey", "attested_by"),
)
ENCRYPTED_MAGIC = b"UGAI-DB-DUMP-AES256GCM-v1"


class MigrationError(RuntimeError):
    """Raised when a migration precondition or postcondition fails."""


def _pgpass_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(":", "\\:")


def _safe_dsn_and_pgpass(dsn: str) -> tuple[str, str | None]:
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    if not dsn.startswith(("postgres://", "postgresql://")):
        raise MigrationError("Database URLs must use postgres:// or postgresql://")
    parts = conninfo_to_dict(dsn)
    password = parts.pop("password", None)
    line = None
    if password:
        fields = (
            parts.get("host") or "localhost",
            parts.get("port") or "5432",
            parts.get("dbname") or "*",
            parts.get("user") or "*",
            password,
        )
        line = ":".join(_pgpass_escape(str(value)) for value in fields)
    return make_conninfo(**parts), line


def _validate_key(encoded: str) -> bytes:
    try:
        key = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise MigrationError("UGAI_EXPORT_ENCRYPTION_KEY_B64 must be valid Base64") from exc
    if len(key) != 32:
        raise MigrationError("UGAI_EXPORT_ENCRYPTION_KEY_B64 must decode to exactly 32 bytes")
    return key


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _encrypt_dump(source: Path, destination: Path, key: bytes) -> str:
    """Stream-encrypt the database dump with AES-256-GCM."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    nonce = os.urandom(12)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(ENCRYPTED_MAGIC)
    with source.open("rb") as reader, destination.open("wb") as writer:
        writer.write(ENCRYPTED_MAGIC)
        writer.write(nonce)
        while block := reader.read(1024 * 1024):
            writer.write(encryptor.update(block))
        writer.write(encryptor.finalize())
        writer.write(encryptor.tag)
    return _sha256_file(destination)



def _decrypt_dump(source: Path, destination: Path, key: bytes) -> str:
    """Authenticate and stream-decrypt a backup previously created by _encrypt_dump."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    if len(key) != 32:
        raise MigrationError("AES-256-GCM requires a 32-byte key")
    if destination.exists():
        raise MigrationError("Refusing to overwrite an existing decrypted dump")
    prefix_length = len(ENCRYPTED_MAGIC) + 12
    file_size = source.stat().st_size
    if file_size < prefix_length + 16:
        raise MigrationError("Encrypted backup is truncated or has an invalid format")

    try:
        with source.open("rb") as reader:
            if reader.read(len(ENCRYPTED_MAGIC)) != ENCRYPTED_MAGIC:
                raise MigrationError("Encrypted backup magic header is invalid")
            nonce = reader.read(12)
            reader.seek(-16, os.SEEK_END)
            tag = reader.read(16)
            reader.seek(prefix_length)
            ciphertext_remaining = file_size - prefix_length - 16
            decryptor = Cipher(
                algorithms.AES(key),
                modes.GCM(nonce, tag),
            ).decryptor()
            decryptor.authenticate_additional_data(ENCRYPTED_MAGIC)
            with destination.open("xb") as writer:
                while ciphertext_remaining:
                    block = reader.read(min(1024 * 1024, ciphertext_remaining))
                    if not block:
                        raise MigrationError("Encrypted backup ended before the ciphertext was complete")
                    ciphertext_remaining -= len(block)
                    writer.write(decryptor.update(block))
                if reader.read(1):
                    raise MigrationError("Encrypted backup has unexpected trailing bytes")
                writer.write(decryptor.finalize())
    except InvalidTag as exc:
        destination.unlink(missing_ok=True)
        raise MigrationError(
            "Encrypted backup authentication failed; key or backup contents are incorrect"
        ) from exc
    except MigrationError:
        destination.unlink(missing_ok=True)
        raise
    except OSError:
        destination.unlink(missing_ok=True)
        raise

    return _sha256_file(destination)

def _utility_major(command: str) -> int:
    try:
        output = subprocess.run(
            [command, "--version"], check=True, capture_output=True, text=True
        ).stdout
    except FileNotFoundError as exc:
        raise MigrationError(f"Required PostgreSQL utility is unavailable: {command}") from exc
    match = re.search(r"\b(\d+)(?:\.\d+)?", output)
    if not match:
        raise MigrationError(f"Cannot parse {command} version")
    return int(match.group(1))


def _run(command: list[str], env: dict[str, str]) -> None:
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, env=env)
    except FileNotFoundError as exc:
        raise MigrationError(f"Required PostgreSQL utility is unavailable: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "unknown PostgreSQL utility error")[-4000:]
        raise MigrationError(f"{command[0]} failed: {detail}") from exc


def _connect(dsn: str):
    import psycopg

    return psycopg.connect(dsn, autocommit=False)


def _row_counts(connection) -> dict[str, int]:
    from psycopg import sql

    objects = connection.execute(
        """
        SELECT n.nspname,c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=ANY(%s) AND c.relkind IN ('r','p')
        ORDER BY n.nspname,c.relname
        """,
        (list(SCHEMAS),),
    ).fetchall()
    result: dict[str, int] = {}
    for schema_name, table_name in objects:
        query = sql.SQL("SELECT count(*) FROM {}.{}").format(
            sql.Identifier(schema_name), sql.Identifier(table_name)
        )
        result[f"{schema_name}.{table_name}"] = int(connection.execute(query).fetchone()[0])
    return result


def _extensions(connection) -> list[dict[str, str]]:
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


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def _server_major(connection) -> int:
    return int(connection.execute("SHOW server_version_num").fetchone()[0]) // 10000


def _target_preflight(connection) -> None:
    present = connection.execute(
        "SELECT nspname FROM pg_namespace WHERE nspname=ANY(%s)",
        (list(SCHEMAS),),
    ).fetchall()
    if present:
        names = ", ".join(sorted(row[0] for row in present))
        raise MigrationError(
            f"Target already has RAG schema(s): {names}. A new empty database is required."
        )
    if connection.execute(
        "SELECT 1 FROM pg_namespace WHERE nspname='auth'"
    ).fetchone():
        raise MigrationError("Target already has an auth schema; use a dedicated new database.")

    available = dict(
        connection.execute(
            "SELECT name,default_version FROM pg_available_extensions "
            "WHERE name=ANY(%s)",
            (list(REQUIRED_EXTENSIONS),),
        ).fetchall()
    )
    for name, minimum in REQUIRED_EXTENSIONS.items():
        if name not in available or _version_tuple(available[name]) < _version_tuple(minimum):
            raise MigrationError(
                f"Target must provide {name} version {minimum} or newer."
            )

    wrong_extension_schema = connection.execute(
        """
        SELECT e.extname,n.nspname
        FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace
        WHERE e.extname IN ('vector','pgcrypto','uuid-ossp')
          AND n.nspname <> 'extensions'
        """
    ).fetchall()
    if wrong_extension_schema:
        details = ", ".join(f"{name}@{schema}" for name, schema in wrong_extension_schema)
        raise MigrationError(f"Existing PostgreSQL extensions are in the wrong schema: {details}")

    unsafe_roles = connection.execute(
        """
        SELECT rolname FROM pg_roles
        WHERE rolname=ANY(%s) AND (rolcanlogin OR rolsuper OR rolbypassrls)
        """,
        (["anon", "authenticated", "service_role", "ugai_runtime"],),
    ).fetchall()
    if unsafe_roles:
        raise MigrationError(
            "Reserved target role(s) must not have LOGIN, SUPERUSER or BYPASSRLS: "
            + ", ".join(row[0] for row in unsafe_roles)
        )


def _bootstrap_target(connection, source_extensions: list[dict[str, str]]) -> None:
    names = {item["name"] for item in source_extensions}
    connection.execute("CREATE SCHEMA IF NOT EXISTS extensions")
    connection.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions")
    connection.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions")
    if "uuid-ossp" in names:
        connection.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA extensions')
    connection.execute(
        """
        DO $roles$
        DECLARE role_name text;
        BEGIN
          FOREACH role_name IN ARRAY
            ARRAY['anon','authenticated','service_role','ugai_runtime']
          LOOP
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=role_name) THEN
              EXECUTE format('CREATE ROLE %I NOLOGIN',role_name);
            END IF;
          END LOOP;
        END
        $roles$
        """
    )
    # Temporary, credential-free stub required to restore the three legacy view
    # dependencies. It is removed after those views are rebound to ugai_identity.
    connection.execute("CREATE SCHEMA IF NOT EXISTS auth")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS auth.users(
          id uuid PRIMARY KEY,
          email text,
          email_confirmed_at timestamptz
        )
        """
    )
    connection.commit()


def _migrate_auth_dependencies(connection) -> None:
    from psycopg import sql

    connection.execute("CREATE SCHEMA IF NOT EXISTS ugai_identity")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS ugai_identity.actors(
          id uuid PRIMARY KEY,
          actor_kind text NOT NULL DEFAULT 'human_or_service_actor',
          active boolean NOT NULL DEFAULT false,
          email_confirmed_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    for qualified_table, constraint, column in ACTOR_FKS:
        schema_name, table_name = qualified_table.split(".", 1)
        connection.execute(
            f"""
            INSERT INTO ugai_identity.actors(id,actor_kind)
            SELECT DISTINCT {column},%s FROM {schema_name}.{table_name}
            WHERE {column} IS NOT NULL
            ON CONFLICT(id) DO NOTHING
            """,
            (table_name,),
        )
        connection.execute(
            f'ALTER TABLE {schema_name}.{table_name} '
            f'DROP CONSTRAINT IF EXISTS "{constraint}"'
        )
        connection.execute(
            f"""
            ALTER TABLE {schema_name}.{table_name}
            ADD CONSTRAINT "{constraint}"
            FOREIGN KEY({column}) REFERENCES ugai_identity.actors(id) ON DELETE RESTRICT
            """
        )

    # Preserve historical curator identifiers without importing auth credentials.
    connection.execute(
        """
        INSERT INTO ugai_identity.actors(id,actor_kind)
        SELECT DISTINCT (metadata->>'curator_user_id')::uuid,
                        'historical_evaluation_curator'
        FROM institutional_rag.evaluation_cases
        WHERE coalesce(metadata->>'curator_user_id','') ~
          '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
        ON CONFLICT(id) DO NOTHING
        """
    )

    # Readiness/reviewer views check auth.users.email_confirmed_at. Repoint those
    # joins to the standalone actor registry so readiness rules are preserved.
    view_rows = connection.execute(
        """
        SELECT schemaname,viewname,definition
        FROM pg_views
        WHERE schemaname=ANY(%s) AND position('auth.users' in definition)>0
        ORDER BY schemaname,viewname
        """,
        (list(SCHEMAS),),
    ).fetchall()
    for schema_name, view_name, definition in view_rows:
        rewritten = definition.replace('"auth"."users"', '"ugai_identity"."actors"')
        rewritten = rewritten.replace("auth.users", "ugai_identity.actors")
        statement = sql.SQL("CREATE OR REPLACE VIEW {}.{} AS ").format(
            sql.Identifier(schema_name), sql.Identifier(view_name)
        ) + sql.SQL(rewritten)
        connection.execute(statement)

    remaining_views = connection.execute(
        """
        SELECT schemaname,viewname FROM pg_views
        WHERE schemaname=ANY(%s) AND position('auth.' in definition)>0
        """,
        (list(SCHEMAS),),
    ).fetchall()
    remaining_functions = connection.execute(
        """
        SELECT n.nspname,p.proname
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname=ANY(%s) AND p.prokind IN ('f','p')
          AND position('auth.' in pg_get_functiondef(p.oid))>0
        """,
        (list(SCHEMAS),),
    ).fetchall()
    remaining_policies = connection.execute(
        """
        SELECT schemaname,tablename,policyname FROM pg_policies
        WHERE schemaname=ANY(%s)
          AND position('auth.' in coalesce(qual,'')||' '||coalesce(with_check,''))>0
        """,
        (list(SCHEMAS),),
    ).fetchall()
    if remaining_views or remaining_functions or remaining_policies:
        raise MigrationError(
            "Unexpected dependencies on Supabase Auth remain; auth schema was not removed."
        )

    connection.execute("DROP SCHEMA auth CASCADE")
    connection.commit()


def _secure_target(connection) -> None:
    connection.execute(
        "GRANT USAGE ON SCHEMA rag,institutional_rag,extensions,ugai_identity TO ugai_runtime"
    )
    connection.execute(
        "GRANT SELECT,INSERT,UPDATE ON ugai_identity.actors TO ugai_runtime"
    )
    connection.execute(
        """
        DO $secure$
        DECLARE item record;
        BEGIN
          FOR item IN
            SELECT n.nspname AS schema_name,c.relname AS object_name,c.relkind,
                   c.relrowsecurity
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=ANY(ARRAY['rag','institutional_rag'])
              AND c.relkind IN ('r','p','v','m')
          LOOP
            IF item.relkind IN ('v','m') THEN
              IF item.relkind='v' THEN
                EXECUTE format(
                  'ALTER VIEW %I.%I SET (security_invoker=true)',
                  item.schema_name,item.object_name
                );
              END IF;
              EXECUTE format(
                'GRANT SELECT ON %I.%I TO ugai_runtime',
                item.schema_name,item.object_name
              );
            ELSE
              EXECUTE format(
                'GRANT SELECT,INSERT,UPDATE ON %I.%I TO ugai_runtime',
                item.schema_name,item.object_name
              );
              IF item.schema_name='rag' AND item.object_name='audit_events' THEN
                EXECUTE format(
                  'REVOKE UPDATE ON %I.%I FROM ugai_runtime',
                  item.schema_name,item.object_name
                );
              END IF;
              IF item.relrowsecurity THEN
                EXECUTE format(
                  'DROP POLICY IF EXISTS ugai_backend_runtime ON %I.%I',
                  item.schema_name,item.object_name
                );
                EXECUTE format(
                  'CREATE POLICY ugai_backend_runtime ON %I.%I '
                  'FOR ALL TO ugai_runtime USING (true) WITH CHECK (true)',
                  item.schema_name,item.object_name
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
        "REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA rag,institutional_rag "
        "FROM PUBLIC,anon,authenticated"
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


def _drive_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    credential_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not credential_file:
        raise MigrationError("GOOGLE_APPLICATION_CREDENTIALS is required")
    credentials = service_account.Credentials.from_service_account_file(
        credential_file,
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _drive_upload(service, path: Path, folder_id: str, mime_type: str) -> str:
    from googleapiclient.http import MediaFileUpload

    request = service.files().create(
        body={
            "name": path.name,
            "mimeType": mime_type,
            "parents": [folder_id],
            "description": "UGAI encrypted RAG migration snapshot",
        },
        media_body=MediaFileUpload(
            str(path), mimetype=mime_type, resumable=True, chunksize=8 * 1024 * 1024
        ),
        fields="id",
        supportsAllDrives=True,
    )
    response = None
    while response is None:
        _, response = request.next_chunk()
    return str(response["id"])


def run_migration(*, apply: bool) -> dict:
    source_dsn = os.environ.get("SOURCE_DATABASE_URL", "")
    target_dsn = os.environ.get("TARGET_DATABASE_URL", "")
    drive_folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")
    if not source_dsn or not target_dsn:
        raise MigrationError("SOURCE_DATABASE_URL and TARGET_DATABASE_URL are required")
    if apply and not drive_folder_id:
        raise MigrationError("GOOGLE_DRIVE_FOLDER_ID is required for --apply")
    key = _validate_key(os.environ.get("UGAI_EXPORT_ENCRYPTION_KEY_B64", "")) if apply else None

    source_safe, source_pass = _safe_dsn_and_pgpass(source_dsn)
    target_safe, target_pass = _safe_dsn_and_pgpass(target_dsn)
    if source_safe == target_safe:
        raise MigrationError("Source and target database connections must differ")

    dump_major = _utility_major("pg_dump")
    restore_major = _utility_major("pg_restore")
    if dump_major < 17 or restore_major < dump_major:
        raise MigrationError("Use pg_dump 17+ and pg_restore at least as new as pg_dump")

    with tempfile.TemporaryDirectory(prefix="ugai-rag-port-") as tmp:
        temp = Path(tmp)
        dump_file = temp / "rag-schemas.dump"
        encrypted_file = temp / "rag-schemas.dump.enc"
        manifest_file = temp / "snapshot-manifest.json"
        pass_file = temp / "pgpass"
        lines = [line for line in (source_pass, target_pass) if line]
        env = os.environ.copy()
        if lines:
            pass_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
            os.chmod(pass_file, 0o600)
            env["PGPASSFILE"] = str(pass_file)

        with _connect(source_dsn) as source, _connect(target_dsn) as target:
            source.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            source_major = _server_major(source)
            target_major = _server_major(target)
            if source_major < 17 or target_major < 17:
                raise MigrationError("Source and target PostgreSQL must both be version 17 or newer")
            source_identity = source.execute(
                "SELECT current_database(),COALESCE(inet_server_addr()::text,'local')"
            ).fetchone()
            target_identity = target.execute(
                "SELECT current_database(),COALESCE(inet_server_addr()::text,'local')"
            ).fetchone()
            if source_identity == target_identity:
                raise MigrationError("Source and target resolve to the same database")
            _target_preflight(target)

            snapshot = source.execute("SELECT pg_export_snapshot()").fetchone()[0]
            source_counts = _row_counts(source)
            source_extensions = _extensions(source)
            extension_map = {item["name"]: item for item in source_extensions}
            for extension, minimum in REQUIRED_EXTENSIONS.items():
                actual = extension_map.get(extension)
                if actual is None or _version_tuple(actual["version"]) < _version_tuple(minimum):
                    raise MigrationError(f"Source extension {extension} must be version {minimum}+")

            manifest = {
                "snapshot_id": str(uuid.uuid4()),
                "created_at": datetime.now(UTC).isoformat(),
                "source_postgresql_major": source_major,
                "schemas": list(SCHEMAS),
                "base_table_count": len(source_counts),
                "row_count": sum(source_counts.values()),
                "table_row_counts": source_counts,
                "extensions": source_extensions,
                "dump_format": "PostgreSQL custom archive",
                "archive_encryption": "AES-256-GCM",
                "migration_state": "snapshot_created",
            }
            if not apply:
                return {
                    "mode": "dry-run",
                    "source_database": source_identity[0],
                    "target_database": target_identity[0],
                    "table_count": len(source_counts),
                    "row_count": sum(source_counts.values()),
                    "table_row_counts": source_counts,
                    "extensions": source_extensions,
                    "snapshot_ready": bool(snapshot),
                }

            if dump_major < source_major:
                raise MigrationError("pg_dump must be at least as new as the source PostgreSQL server")
            _run(
                [
                    "pg_dump",
                    "--format=custom",
                    "--compress=6",
                    "--no-owner",
                    "--no-privileges",
                    "--schema=rag",
                    "--schema=institutional_rag",
                    f"--snapshot={snapshot}",
                    f"--file={dump_file}",
                    source_safe,
                ],
                env,
            )
            source.commit()
            assert key is not None
            encrypted_hash = _encrypt_dump(dump_file, encrypted_file, key)
            manifest["encrypted_dump_sha256"] = encrypted_hash
            manifest["dump_size_bytes"] = dump_file.stat().st_size
            manifest["encrypted_dump_size_bytes"] = encrypted_file.stat().st_size
            manifest["migration_state"] = "encrypted_snapshot_archived_pending_restore"
            manifest_file.write_text(
                json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
            )

            drive = _drive_service()
            archive_dump_id = _drive_upload(
                drive, encrypted_file, drive_folder_id, "application/octet-stream"
            )
            archive_manifest_id = _drive_upload(
                drive, manifest_file, drive_folder_id, "application/json"
            )

            _bootstrap_target(target, source_extensions)
            _run(
                [
                    "pg_restore",
                    "--exit-on-error",
                    "--single-transaction",
                    "--no-owner",
                    "--no-privileges",
                    f"--dbname={target_safe}",
                    str(dump_file),
                ],
                env,
            )
            _migrate_auth_dependencies(target)
            _secure_target(target)

            target_counts = _row_counts(target)
            if source_counts != target_counts:
                differences = {
                    name: {"source": source_counts.get(name), "target": target_counts.get(name)}
                    for name in sorted(set(source_counts) | set(target_counts))
                    if source_counts.get(name) != target_counts.get(name)
                }
                raise MigrationError(
                    "Exact row-count verification failed: " + json.dumps(differences, sort_keys=True)
                )

            target_extensions = {item["name"]: item for item in _extensions(target)}
            for extension, minimum in REQUIRED_EXTENSIONS.items():
                actual = target_extensions.get(extension)
                if actual is None or _version_tuple(actual["version"]) < _version_tuple(minimum):
                    raise MigrationError(f"Target extension {extension} is missing or too old")

            manifest["migration_state"] = "restored_and_row_count_verified"
            manifest["target_postgresql_major"] = target_major
            manifest["verified_table_row_counts"] = target_counts
            manifest["google_drive"] = {
                "encrypted_dump_file_id": archive_dump_id,
                "initial_manifest_file_id": archive_manifest_id,
            }
            manifest_file.write_text(
                json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
            )
            verified_manifest_id = _drive_upload(
                drive,
                manifest_file,
                drive_folder_id,
                "application/json",
            )
            return {
                "mode": "apply",
                "state": manifest["migration_state"],
                "table_count": len(target_counts),
                "row_count": sum(target_counts.values()),
                "verified_manifest_file_id": verified_manifest_id,
                "encrypted_dump_file_id": archive_dump_id,
                "table_row_counts": target_counts,
            }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Archive an encrypted snapshot and restore it to a new empty PostgreSQL database",
    )
    mode.add_argument(
        "--decrypt-backup",
        type=Path,
        help="Authenticate and decrypt an encrypted backup file from Google Drive",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="New output file path required with --decrypt-backup",
    )
    args = parser.parse_args()

    if args.decrypt_backup:
        if args.output is None:
            parser.error("--output is required with --decrypt-backup")
        try:
            key = _validate_key(os.environ.get("UGAI_EXPORT_ENCRYPTION_KEY_B64", ""))
            digest = _decrypt_dump(args.decrypt_backup, args.output, key)
            print(
                json.dumps(
                    {
                        "state": "backup_authenticated_and_decrypted",
                        "output": str(args.output),
                        "plaintext_sha256": digest,
                    },
                    indent=2,
                )
            )
            return 0
        except (MigrationError, OSError, ValueError) as exc:
            print(f"RAG backup recovery failed: {exc}", file=sys.stderr)
            return 2

    if args.output is not None:
        parser.error("--output can only be used with --decrypt-backup")

    try:
        import psycopg
        from googleapiclient.errors import HttpError
    except ImportError:
        print(
            "Install the optional dependencies with: pip install -e '.[rag-migration]'",
            file=sys.stderr,
        )
        return 2

    try:
        print(json.dumps(run_migration(apply=args.apply), indent=2, sort_keys=True))
        return 0
    except (
        MigrationError,
        psycopg.Error,
        HttpError,
        OSError,
        ValueError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"RAG migration failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

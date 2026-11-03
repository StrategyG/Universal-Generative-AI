from __future__ import annotations

import base64
import os
from pathlib import Path

import pytest

from ugai_decision.rag_migration import (
    ENCRYPTED_MAGIC,
    MigrationError,
    _decrypt_dump,
    _encrypt_dump,
    _pgpass_escape,
    _validate_key,
)


def test_pgpass_escapes_delimiters():
    assert _pgpass_escape(r"db:user\name") == r"db\:user\\name"


def test_encryption_key_requires_32_bytes():
    with pytest.raises(MigrationError, match="32 bytes"):
        _validate_key(base64.b64encode(b"too short").decode())
    key = os.urandom(32)
    assert _validate_key(base64.b64encode(key).decode()) == key


def test_dump_encryption_is_streamed_and_tagged(tmp_path: Path):
    source = tmp_path / "dump"
    encrypted = tmp_path / "dump.enc"
    content = os.urandom(2_500_000)
    source.write_bytes(content)
    key = os.urandom(32)
    digest = _encrypt_dump(source, encrypted, key)
    output = encrypted.read_bytes()
    assert output.startswith(ENCRYPTED_MAGIC)
    assert len(output) == len(ENCRYPTED_MAGIC) + 12 + len(content) + 16
    assert len(digest) == 64
    assert encrypted.read_bytes() != content


def test_encrypted_backup_can_be_authenticated_and_decrypted(tmp_path: Path):
    source = tmp_path / "dump"
    encrypted = tmp_path / "dump.enc"
    restored = tmp_path / "restored.dump"
    content = os.urandom(1_250_000)
    key = os.urandom(32)
    source.write_bytes(content)
    _encrypt_dump(source, encrypted, key)
    restored_sha256 = _decrypt_dump(encrypted, restored, key)
    assert restored.read_bytes() == content
    assert len(restored_sha256) == 64


def test_tampered_backup_is_rejected_without_leaving_partial_plaintext(tmp_path: Path):
    source = tmp_path / "dump"
    encrypted = tmp_path / "dump.enc"
    restored = tmp_path / "restored.dump"
    content = b"source database backup"
    key = os.urandom(32)
    source.write_bytes(content)
    _encrypt_dump(source, encrypted, key)
    corrupted = bytearray(encrypted.read_bytes())
    corrupted[-1] ^= 0x01
    encrypted.write_bytes(corrupted)
    with pytest.raises(MigrationError, match="authentication failed"):
        _decrypt_dump(encrypted, restored, key)
    assert not restored.exists()


class _FakeRequest:
    def __init__(self, response):
        self.response = response

    def execute(self):
        return self.response


class _FakeDriveFiles:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def get(self, **kwargs):
        self.kwargs = kwargs
        return _FakeRequest(self.response)


class _FakeDrive:
    def __init__(self, response):
        self.file_api = _FakeDriveFiles(response)

    def files(self):
        return self.file_api


def test_drive_destination_requires_shared_drive_and_write_capability():
    from ugai_decision.rag_migration import _drive_folder_info

    drive = _FakeDrive(
        {
            "id": "folder-123",
            "name": "Restricted RAG backups",
            "mimeType": "application/vnd.google-apps.folder",
            "driveId": "shared-drive-456",
            "capabilities": {"canAddChildren": True},
        }
    )
    assert _drive_folder_info(drive, "folder-123") == {
        "id": "folder-123",
        "name": "Restricted RAG backups",
        "drive_id": "shared-drive-456",
    }
    assert drive.file_api.kwargs["supportsAllDrives"] is True


def test_drive_destination_rejects_my_drive_folder_for_service_account():
    from ugai_decision.rag_migration import _drive_folder_info

    drive = _FakeDrive(
        {
            "id": "folder-123",
            "name": "My Drive folder",
            "mimeType": "application/vnd.google-apps.folder",
            "capabilities": {"canAddChildren": True},
        }
    )
    with pytest.raises(MigrationError, match="Shared Drive"):
        _drive_folder_info(drive, "folder-123")


def test_drive_destination_rejects_folder_without_add_permission():
    from ugai_decision.rag_migration import _drive_folder_info

    drive = _FakeDrive(
        {
            "id": "folder-123",
            "name": "Read-only folder",
            "mimeType": "application/vnd.google-apps.folder",
            "driveId": "shared-drive-456",
            "capabilities": {"canAddChildren": False},
        }
    )
    with pytest.raises(MigrationError, match="Contributor"):
        _drive_folder_info(drive, "folder-123")


class _FakeRows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class _FakeRoutineConnection:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, query, params):
        assert "p.prosecdef" in query
        assert params == (["rag", "institutional_rag"],)
        return _FakeRows(self.rows)


def test_security_definer_guard_allows_only_invoker_routines():
    from ugai_decision.rag_migration import _assert_no_security_definer

    _assert_no_security_definer(_FakeRoutineConnection([]))


def test_security_definer_guard_fails_closed_with_routine_names():
    from ugai_decision.rag_migration import _assert_no_security_definer

    connection = _FakeRoutineConnection(
        [("institutional_rag", "unsafe_review", "p_actor_id uuid")]
    )
    with pytest.raises(MigrationError, match="SECURITY DEFINER.*unsafe_review"):
        _assert_no_security_definer(connection)


class _FakeAuthFkConnection:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, query, params):
        assert "con.contype='f'" in query
        assert "target_ns.nspname='auth'" in query
        assert params == (["rag", "institutional_rag"],)
        return _FakeRows(self.rows)


def test_auth_dependency_guard_accepts_only_mapped_auth_foreign_keys():
    from ugai_decision.rag_migration import _assert_no_auth_foreign_keys

    _assert_no_auth_foreign_keys(_FakeAuthFkConnection([]))


def test_auth_dependency_guard_rejects_unmapped_foreign_keys():
    from ugai_decision.rag_migration import _assert_no_auth_foreign_keys

    connection = _FakeAuthFkConnection(
        [("institutional_rag", "new_table", "new_table_actor_fkey", "auth", "users")]
    )
    with pytest.raises(MigrationError, match="Unmapped foreign keys.*new_table_actor_fkey"):
        _assert_no_auth_foreign_keys(connection)



def test_source_database_url_requires_tls():
    from ugai_decision.rag_migration import _safe_dsn_and_pgpass

    with pytest.raises(MigrationError, match="must enforce TLS"):
        _safe_dsn_and_pgpass("postgresql://user:password@db.example.com:5432/rag", require_ssl=True)

    safe_dsn, pgpass = _safe_dsn_and_pgpass(
        "postgresql://user:password@db.example.com:5432/rag?sslmode=require",
        require_ssl=True,
    )
    assert "password" not in safe_dsn
    assert "sslmode=require" in safe_dsn
    assert pgpass is not None and pgpass.endswith(":password")


class _PreflightResult:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _FakeTargetPreflightConnection:
    def __init__(self, *, schemas=(), public_objects=()):
        self.schemas = list(schemas)
        self.public_objects = list(public_objects)

    def execute(self, query, params=None):
        if "nspname=ANY" in query:
            return _PreflightResult([])
        if "nspname='auth'" in query:
            return _PreflightResult([])
        if "nspname NOT IN" in query:
            return _PreflightResult(self.schemas)
        if "n.nspname='public'" in query:
            return _PreflightResult(self.public_objects)
        if "pg_available_extensions" in query:
            return _PreflightResult([("vector", "0.8.2"), ("pgcrypto", "1.3")])
        if "n.nspname <> 'extensions'" in query:
            return _PreflightResult([])
        if "rolname=ANY" in query:
            return _PreflightResult([])
        raise AssertionError(f"Unexpected preflight query: {query}")


def test_target_preflight_accepts_fresh_empty_database():
    from ugai_decision.rag_migration import _target_preflight

    _target_preflight(_FakeTargetPreflightConnection())


def test_target_preflight_rejects_unexpected_schema():
    from ugai_decision.rag_migration import _target_preflight

    connection = _FakeTargetPreflightConnection(schemas=[("legacy_app",)])
    with pytest.raises(MigrationError, match="unexpected schema"):
        _target_preflight(connection)


def test_target_preflight_rejects_objects_in_public_schema():
    from ugai_decision.rag_migration import _target_preflight

    connection = _FakeTargetPreflightConnection(public_objects=[("customer_data",)])
    with pytest.raises(MigrationError, match="public schema contains objects"):
        _target_preflight(connection)

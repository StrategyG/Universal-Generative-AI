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

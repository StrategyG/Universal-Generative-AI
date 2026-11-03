from __future__ import annotations

import base64
import os
from pathlib import Path

import pytest

from ugai_decision.rag_migration import (
    ENCRYPTED_MAGIC,
    MigrationError,
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

"""Authenticated encryption for persisted UGAI task inputs.

The encryption key is supplied by deployment secret management. It is never
stored in PostgreSQL, task metadata, logs, or API responses.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


class TaskPayloadCipher:
    """Fernet-backed envelope with explicit key ID and canonical JSON digest."""

    def __init__(self, key: str, *, key_id: str = "v1") -> None:
        if not isinstance(key, str) or not key:
            raise ValueError("task_payload_encryption_key_required")
        if not isinstance(key_id, str) or not key_id.strip() or len(key_id) > 64:
            raise ValueError("task_payload_key_id_invalid")
        try:
            self._fernet = Fernet(key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise ValueError("task_payload_encryption_key_invalid") from exc
        self.key_id = key_id

    @staticmethod
    def canonical_bytes(payload: Mapping[str, Any]) -> bytes:
        if not isinstance(payload, Mapping):
            raise TypeError("task_payload_must_be_object")
        try:
            data = json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("task_payload_must_be_finite_json") from exc
        if not 1 <= len(data) <= 128 * 1024:
            raise ValueError("task_payload_size_invalid")
        return data

    def encrypt(self, payload: Mapping[str, Any]) -> tuple[bytes, str]:
        plaintext = self.canonical_bytes(payload)
        encrypted = self._fernet.encrypt(plaintext)
        if len(encrypted) > 256 * 1024:
            raise ValueError("encrypted_task_payload_size_invalid")
        return encrypted, hashlib.sha256(plaintext).hexdigest()

    def decrypt(self, encrypted: bytes, *, expected_sha256: str) -> dict[str, Any]:
        if not isinstance(encrypted, bytes) or not 1 <= len(encrypted) <= 256 * 1024:
            raise ValueError("encrypted_task_payload_size_invalid")
        if (
            not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
            or any(char not in "0123456789abcdef" for char in expected_sha256)
        ):
            raise ValueError("task_payload_digest_invalid")
        try:
            plaintext = self._fernet.decrypt(encrypted, ttl=None)
        except (InvalidToken, TypeError) as exc:
            raise ValueError("task_payload_decryption_failed") from exc
        if not hashlib.sha256(plaintext).hexdigest() == expected_sha256:
            raise ValueError("task_payload_integrity_check_failed")
        value = json.loads(plaintext)
        if not isinstance(value, dict):
            raise ValueError("task_payload_must_decode_to_object")
        return value

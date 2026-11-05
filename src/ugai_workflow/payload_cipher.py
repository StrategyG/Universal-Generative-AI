"""Authenticated encryption for persisted UGAI task inputs with key rotation.

The active and previous encryption keys are supplied by deployment secret
management. Key material is never stored in PostgreSQL, task metadata, logs,
or API responses.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


class TaskPayloadCipher:
    """Fernet key ring with explicit key IDs and canonical payload digests.

    New payloads are encrypted only with the active key. Existing rows retain
    their key ID and are decrypted using the matching active/previous key.
    Removing a previous key is safe only after all rows with that key ID have
    been re-encrypted or explicitly expired under the retention policy.
    """

    def __init__(
        self,
        key: str,
        *,
        key_id: str = "v1",
        previous_keys: Mapping[str, str] | None = None,
    ) -> None:
        self._validate_key_id(key_id)
        self.key_id = key_id
        self._fernets: dict[str, Fernet] = {
            key_id: self._build_fernet(key, label="active")
        }
        if previous_keys is not None:
            if not isinstance(previous_keys, Mapping):
                raise ValueError("task_payload_previous_keys_must_be_object")
            for previous_id, previous_key in previous_keys.items():
                self._validate_key_id(previous_id)
                if previous_id == key_id:
                    raise ValueError("task_payload_key_id_duplicate")
                if not isinstance(previous_key, str) or not previous_key:
                    raise ValueError("task_payload_previous_key_invalid")
                if previous_id in self._fernets:
                    raise ValueError("task_payload_key_id_duplicate")
                self._fernets[previous_id] = self._build_fernet(
                    previous_key, label="previous"
                )

    @staticmethod
    def _validate_key_id(key_id: str) -> None:
        if (
            not isinstance(key_id, str)
            or not key_id.strip()
            or len(key_id) > 64
            or any(ord(ch) < 33 or ord(ch) > 126 for ch in key_id)
        ):
            raise ValueError("task_payload_key_id_invalid")

    @staticmethod
    def _build_fernet(key: str, *, label: str) -> Fernet:
        if not isinstance(key, str) or not key:
            raise ValueError(f"task_payload_{label}_key_required")
        try:
            return Fernet(key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise ValueError(f"task_payload_{label}_key_invalid") from exc

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
        encrypted = self._fernets[self.key_id].encrypt(plaintext)
        if len(encrypted) > 256 * 1024:
            raise ValueError("encrypted_task_payload_size_invalid")
        return encrypted, hashlib.sha256(plaintext).hexdigest()

    def decrypt(
        self,
        encrypted: bytes,
        *,
        expected_sha256: str,
        key_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(encrypted, bytes) or not 1 <= len(encrypted) <= 256 * 1024:
            raise ValueError("encrypted_task_payload_size_invalid")
        if (
            not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
            or any(char not in "0123456789abcdef" for char in expected_sha256)
        ):
            raise ValueError("task_payload_digest_invalid")
        selected_id = key_id or self.key_id
        try:
            fernet = self._fernets[selected_id]
        except KeyError as exc:
            raise ValueError("task_payload_decryption_key_unavailable") from exc
        try:
            plaintext = fernet.decrypt(encrypted, ttl=None)
        except (InvalidToken, TypeError) as exc:
            raise ValueError("task_payload_decryption_failed") from exc
        if hashlib.sha256(plaintext).hexdigest() != expected_sha256:
            raise ValueError("task_payload_integrity_check_failed")
        value = json.loads(plaintext)
        if not isinstance(value, dict):
            raise ValueError("task_payload_must_decode_to_object")
        return value

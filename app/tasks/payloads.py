"""Authenticated encryption for bounded task inputs stored outside workflow metadata."""

from __future__ import annotations

import base64
import json
import re
import secrets
from dataclasses import dataclass
from typing import Any, Mapping
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_MAX_PAYLOAD_BYTES = 64 * 1024
_KEY_VERSION = re.compile(r"^[A-Za-z0-9._-]{1,32}$")


class TaskPayloadIntegrityError(ValueError):
    """Encrypted task input is corrupt or bound to a different tenant/task."""


@dataclass(frozen=True, slots=True)
class EncryptedTaskPayload:
    ciphertext: bytes
    nonce: bytes
    key_version: str


class TaskPayloadCipher:
    """AES-256-GCM payload envelope with tenant/task/key-version AAD binding.

    The key must be injected by an external secret manager. This class never reads
    keys from source files, prompts, database rows or model output.
    """

    def __init__(self, key: bytes, *, key_version: str) -> None:
        if not isinstance(key, bytes) or len(key) != 32:
            raise ValueError("task_payload_key_must_be_32_bytes")
        if not isinstance(key_version, str) or not _KEY_VERSION.fullmatch(key_version):
            raise ValueError("task_payload_key_version_invalid")
        self._aead = AESGCM(key)
        self.key_version = key_version

    @classmethod
    def from_base64(cls, value: str, *, key_version: str) -> TaskPayloadCipher:
        if not isinstance(value, str) or not value or len(value) > 128:
            raise ValueError("task_payload_key_missing_or_invalid")
        try:
            key = base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True)
        except (UnicodeEncodeError, ValueError) as exc:
            raise ValueError("task_payload_key_must_be_valid_base64") from exc
        return cls(key, key_version=key_version)

    @staticmethod
    def _aad(tenant_id: str, task_id: UUID, key_version: str) -> bytes:
        if not isinstance(tenant_id, str) or not tenant_id.strip() or len(tenant_id) > 128:
            raise ValueError("task_payload_tenant_invalid")
        return f"ugai-task-payload:v1:{key_version}:{tenant_id}:{task_id}".encode("utf-8")

    def encrypt_bytes(self, plaintext: bytes, *, tenant_id: str, task_id: UUID) -> EncryptedTaskPayload:
        if not isinstance(plaintext, bytes) or not plaintext or len(plaintext) > _MAX_PAYLOAD_BYTES:
            raise ValueError("task_payload_size_invalid")
        nonce = secrets.token_bytes(12)
        ciphertext = self._aead.encrypt(
            nonce,
            plaintext,
            self._aad(tenant_id, task_id, self.key_version),
        )
        return EncryptedTaskPayload(ciphertext, nonce, self.key_version)

    def encrypt_json(
        self, payload: Mapping[str, Any], *, tenant_id: str, task_id: UUID
    ) -> EncryptedTaskPayload:
        if not isinstance(payload, Mapping):
            raise TypeError("task_payload_must_be_an_object")
        try:
            plaintext = json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("task_payload_must_be_finite_json") from exc
        return self.encrypt_bytes(plaintext, tenant_id=tenant_id, task_id=task_id)

    def decrypt_bytes(
        self,
        envelope: EncryptedTaskPayload,
        *,
        tenant_id: str,
        task_id: UUID,
    ) -> bytes:
        if not isinstance(envelope, EncryptedTaskPayload):
            raise TypeError("encrypted_task_payload_required")
        if envelope.key_version != self.key_version or len(envelope.nonce) != 12:
            raise TaskPayloadIntegrityError("task_payload_envelope_version_or_nonce_invalid")
        try:
            return self._aead.decrypt(
                envelope.nonce,
                envelope.ciphertext,
                self._aad(tenant_id, task_id, envelope.key_version),
            )
        except InvalidTag as exc:
            raise TaskPayloadIntegrityError("task_payload_authentication_failed") from exc

    def decrypt_json(
        self,
        envelope: EncryptedTaskPayload,
        *,
        tenant_id: str,
        task_id: UUID,
    ) -> dict[str, Any]:
        try:
            value = json.loads(self.decrypt_bytes(envelope, tenant_id=tenant_id, task_id=task_id))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TaskPayloadIntegrityError("task_payload_json_invalid") from exc
        if not isinstance(value, dict):
            raise TaskPayloadIntegrityError("task_payload_json_not_object")
        return value

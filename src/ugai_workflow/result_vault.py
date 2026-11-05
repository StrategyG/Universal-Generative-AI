"""Tenant/actor/project-scoped encrypted persistence for task results."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ugai_workflow.input_vault import WorkflowInputError, WorkflowInputNotFound

_KEY_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_RESULT_BYTES = 256 * 1024


class WorkflowResultConflict(WorkflowInputError):
    """A task already has a different immutable result."""


class WorkflowResultVault:
    """AES-256-GCM result store backed by the restricted workflow database role."""

    def __init__(
        self,
        *,
        pool: Any,
        active_key_id: str,
        keyring: Mapping[str, bytes],
    ) -> None:
        if pool is None or not callable(getattr(pool, "acquire", None)):
            raise ValueError("async_postgres_pool_required")
        if not isinstance(active_key_id, str) or not _KEY_ID.fullmatch(active_key_id):
            raise ValueError("workflow_result_active_key_id_invalid")
        if not isinstance(keyring, Mapping) or active_key_id not in keyring:
            raise ValueError("workflow_result_active_key_missing")
        checked: dict[str, bytes] = {}
        for key_id, key in keyring.items():
            if not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id):
                raise ValueError("workflow_result_key_id_invalid")
            if not isinstance(key, bytes) or len(key) != 32:
                raise ValueError("workflow_result_keys_must_be_32_bytes")
            checked[key_id] = key
        self._pool = pool
        self._active_key_id = active_key_id
        self._keyring = checked

    @staticmethod
    def _aad(
        *,
        tenant_id: str,
        actor_id: str,
        project_id: str,
        task_id: UUID,
        key_id: str,
    ) -> bytes:
        # Canonical JSON preserves scope boundaries for AES-GCM authentication.
        return json.dumps(
            [
                "ugai-workflow-result:v1",
                tenant_id,
                actor_id,
                project_id,
                str(task_id),
                key_id,
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def _canonical_payload(payload: Mapping[str, Any]) -> tuple[bytes, str]:
        if not isinstance(payload, Mapping):
            raise TypeError("workflow_result_must_be_object")
        try:
            encoded = json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("workflow_result_must_be_finite_json") from exc
        if not encoded or len(encoded) > _MAX_RESULT_BYTES:
            raise ValueError("workflow_result_size_out_of_bounds")
        return encoded, hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _validate_scope(
        *, tenant_id: str, actor_id: str, project_id: str, task_id: UUID
    ) -> None:
        for name, value, limit in (
            ("tenant_id", tenant_id, 128),
            ("actor_id", actor_id, 255),
            ("project_id", project_id, 128),
        ):
            if not isinstance(value, str) or not value.strip() or len(value) > limit:
                raise ValueError(f"{name}_invalid")
        if not isinstance(task_id, UUID):
            raise ValueError("workflow_task_id_invalid")

    async def put(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        project_id: str,
        task_id: UUID,
        payload: Mapping[str, Any],
    ) -> str:
        self._validate_scope(
            tenant_id=tenant_id,
            actor_id=actor_id,
            project_id=project_id,
            task_id=task_id,
        )
        plaintext, digest = self._canonical_payload(payload)
        key_id = self._active_key_id
        nonce = secrets.token_bytes(12)
        aad = self._aad(
            tenant_id=tenant_id,
            actor_id=actor_id,
            project_id=project_id,
            task_id=task_id,
            key_id=key_id,
        )
        ciphertext = AESGCM(self._keyring[key_id]).encrypt(nonce, plaintext, aad)

        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.fetchval(
                    "SELECT set_config('app.ugai_tenant_id', $1, true)", tenant_id
                )
                await connection.fetchval(
                    "SELECT set_config('app.ugai_actor_id', $1, true)", actor_id
                )
                row = await connection.fetchrow(
                    """
                    INSERT INTO ugai_workflow.results (
                        tenant_id, task_id, actor_id, project_id,
                        key_id, nonce, ciphertext, result_digest
                    )
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                    ON CONFLICT (tenant_id, task_id) DO NOTHING
                    RETURNING result_digest
                    """,
                    tenant_id, task_id, actor_id, project_id,
                    key_id, nonce, ciphertext, digest,
                )
                if row is not None:
                    return row["result_digest"]
                existing = await connection.fetchrow(
                    """
                    SELECT actor_id, project_id, result_digest
                    FROM ugai_workflow.results
                    WHERE tenant_id = $1 AND task_id = $2
                    """,
                    tenant_id, task_id,
                )
                if (
                    existing is None
                    or existing["actor_id"] != actor_id
                    or existing["project_id"] != project_id
                    or existing["result_digest"] != digest
                ):
                    raise WorkflowResultConflict("workflow_result_conflict")
                return existing["result_digest"]

    async def get(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        project_id: str,
        task_id: UUID,
    ) -> dict[str, Any]:
        self._validate_scope(
            tenant_id=tenant_id,
            actor_id=actor_id,
            project_id=project_id,
            task_id=task_id,
        )
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.fetchval(
                    "SELECT set_config('app.ugai_tenant_id', $1, true)", tenant_id
                )
                await connection.fetchval(
                    "SELECT set_config('app.ugai_actor_id', $1, true)", actor_id
                )
                row = await connection.fetchrow(
                    """
                    SELECT key_id, nonce, ciphertext, result_digest
                    FROM ugai_workflow.results
                    WHERE tenant_id = $1 AND actor_id = $2
                      AND project_id = $3 AND task_id = $4
                    """,
                    tenant_id, actor_id, project_id, task_id,
                )
        if row is None:
            raise WorkflowInputNotFound("workflow_result_not_found")
        key_id = row["key_id"]
        key = self._keyring.get(key_id)
        if key is None:
            raise WorkflowInputError("workflow_result_encryption_key_unavailable")
        aad = self._aad(
            tenant_id=tenant_id,
            actor_id=actor_id,
            project_id=project_id,
            task_id=task_id,
            key_id=key_id,
        )
        try:
            plaintext = AESGCM(key).decrypt(row["nonce"], row["ciphertext"], aad)
        except Exception as exc:
            raise WorkflowInputError("workflow_result_authentication_failed") from exc
        digest = hashlib.sha256(plaintext).hexdigest()
        if not secrets.compare_digest(digest, row["result_digest"]) or not _SHA256.fullmatch(digest):
            raise WorkflowInputError("workflow_result_digest_mismatch")
        try:
            result = json.loads(plaintext)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WorkflowInputError("workflow_result_payload_corrupt") from exc
        if not isinstance(result, dict):
            raise WorkflowInputError("workflow_result_payload_invalid")
        return result

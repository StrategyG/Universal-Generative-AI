"""Tenant- and actor-scoped encrypted storage for durable UGAI task inputs.

Only ciphertext, scope metadata, and a SHA-256 digest are persisted. Key
material is injected by the deployment secret manager; it is never stored in
PostgreSQL or emitted to logs.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_KEY_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_MAX_INPUT_BYTES = 32 * 1024


class WorkflowInputError(RuntimeError):
    """Base error for protected task input operations."""


class WorkflowInputNotFound(WorkflowInputError):
    """The protected input does not exist in the caller's scope."""


class WorkflowInputConflict(WorkflowInputError):
    """An idempotency key was reused with a different protected input."""


@dataclass(frozen=True, slots=True)
class StoredWorkflowInput:
    input_ref: UUID
    input_digest: str
    project_id: str
    workspace_id: UUID
    expires_at: datetime


class WorkflowInputVault:
    """AES-256-GCM vault backed by the restricted UGAI workflow PostgreSQL role."""

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
            raise ValueError("workflow_input_active_key_id_invalid")
        if not isinstance(keyring, Mapping) or active_key_id not in keyring:
            raise ValueError("workflow_input_active_key_missing")
        checked: dict[str, bytes] = {}
        for key_id, key in keyring.items():
            if not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id):
                raise ValueError("workflow_input_key_id_invalid")
            if not isinstance(key, bytes) or len(key) != 32:
                raise ValueError("workflow_input_keys_must_be_32_bytes")
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
        workspace_id: UUID,
        input_ref: UUID,
        key_id: str,
    ) -> bytes:
        return (
            "ugai-workflow-input:v1:"
            f"{tenant_id}:{actor_id}:{project_id}:{workspace_id}:{input_ref}:{key_id}"
        ).encode("utf-8")

    @staticmethod
    def _canonical_payload(payload: Mapping[str, Any]) -> tuple[bytes, str]:
        if not isinstance(payload, Mapping):
            raise TypeError("workflow_input_must_be_object")
        try:
            encoded = json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("workflow_input_must_be_finite_json") from exc
        if not encoded or len(encoded) > _MAX_INPUT_BYTES:
            raise ValueError("workflow_input_size_out_of_bounds")
        return encoded, hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _validate_scope(
        *, tenant_id: str, actor_id: str, project_id: str, idempotency_key: str
    ) -> None:
        for name, value, limit in (
            ("tenant_id", tenant_id, 128),
            ("actor_id", actor_id, 255),
            ("project_id", project_id, 128),
        ):
            if not isinstance(value, str) or not value.strip() or len(value) > limit:
                raise ValueError(f"{name}_invalid")
        if not _IDEMPOTENCY.fullmatch(idempotency_key or ""):
            raise ValueError("idempotency_key_invalid")

    async def put(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        project_id: str,
        workspace_id: UUID,
        notebook_id: UUID | None,
        idempotency_key: str,
        payload: Mapping[str, Any],
    ) -> StoredWorkflowInput:
        self._validate_scope(
            tenant_id=tenant_id,
            actor_id=actor_id,
            project_id=project_id,
            idempotency_key=idempotency_key,
        )
        if not isinstance(workspace_id, UUID) or (
            notebook_id is not None and not isinstance(notebook_id, UUID)
        ):
            raise ValueError("workflow_workspace_or_notebook_id_invalid")
        plaintext, digest = self._canonical_payload(payload)
        input_ref = uuid4()
        key_id = self._active_key_id
        nonce = secrets.token_bytes(12)
        aad = self._aad(
            tenant_id=tenant_id,
            actor_id=actor_id,
            project_id=project_id,
            workspace_id=workspace_id,
            input_ref=input_ref,
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
                    INSERT INTO ugai_workflow.inputs (
                        input_ref, tenant_id, actor_id, project_id, workspace_id,
                        notebook_id, key_id, nonce, ciphertext, payload_digest,
                        idempotency_key
                    )
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                    ON CONFLICT (tenant_id, actor_id, idempotency_key) DO NOTHING
                    RETURNING input_ref, payload_digest AS input_digest, project_id, workspace_id, expires_at
                    """,
                    input_ref, tenant_id, actor_id, project_id, workspace_id,
                    notebook_id, key_id, nonce, ciphertext, digest, idempotency_key,
                )
                if row is None:
                    existing = await connection.fetchrow(
                        """
                        SELECT input_ref, payload_digest AS input_digest, project_id,
                               workspace_id, notebook_id, expires_at
                        FROM ugai_workflow.inputs
                        WHERE tenant_id = $1 AND actor_id = $2 AND idempotency_key = $3
                        """,
                        tenant_id, actor_id, idempotency_key,
                    )
                    if existing is None or (
                        existing["input_digest"] != digest
                        or existing["project_id"] != project_id
                        or existing["workspace_id"] != workspace_id
                        or existing["notebook_id"] != notebook_id
                        or existing["expires_at"] <= datetime.now(existing["expires_at"].tzinfo)
                    ):
                        raise WorkflowInputConflict("workflow_input_idempotency_conflict")
                    return StoredWorkflowInput(
                        input_ref=existing["input_ref"],
                        input_digest=existing["input_digest"],
                        project_id=existing["project_id"],
                        workspace_id=existing["workspace_id"],
                        expires_at=existing["expires_at"],
                    )
                return StoredWorkflowInput(
                    input_ref=row["input_ref"],
                    input_digest=row["input_digest"],
                    project_id=row["project_id"],
                    workspace_id=row["workspace_id"],
                    expires_at=row["expires_at"],
                )

    async def get_metadata(
        self,
        *,
        input_ref: UUID,
        tenant_id: str,
        actor_id: str,
    ) -> StoredWorkflowInput:
        self._validate_scope(
            tenant_id=tenant_id,
            actor_id=actor_id,
            project_id="scope-check",
            idempotency_key="scope-check-0001",
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
                    SELECT input_ref, payload_digest AS input_digest, project_id,
                           workspace_id, expires_at
                    FROM ugai_workflow.inputs
                    WHERE input_ref = $1 AND tenant_id = $2 AND actor_id = $3
                      AND expires_at > clock_timestamp()
                    """,
                    input_ref, tenant_id, actor_id,
                )
        if row is None:
            raise WorkflowInputNotFound("workflow_input_not_found")
        return StoredWorkflowInput(
            input_ref=row["input_ref"],
            input_digest=row["input_digest"],
            project_id=row["project_id"],
            workspace_id=row["workspace_id"],
            expires_at=row["expires_at"],
        )

    async def resolve(
        self,
        *,
        input_ref: UUID,
        tenant_id: str,
        actor_id: str,
        expected_project_id: str,
    ) -> Mapping[str, Any]:
        self._validate_scope(
            tenant_id=tenant_id,
            actor_id=actor_id,
            project_id=expected_project_id,
            idempotency_key="scope-check-0001",
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
                    SELECT project_id, workspace_id, key_id, nonce, ciphertext,
                           payload_digest, expires_at
                    FROM ugai_workflow.inputs
                    WHERE input_ref = $1 AND tenant_id = $2 AND actor_id = $3
                      AND expires_at > clock_timestamp()
                    """,
                    input_ref, tenant_id, actor_id,
                )
        if row is None or row["project_id"] != expected_project_id:
            raise WorkflowInputNotFound("workflow_input_not_found")
        key_id = row["key_id"]
        key = self._keyring.get(key_id)
        if key is None:
            raise WorkflowInputError("workflow_input_encryption_key_unavailable")
        aad = self._aad(
            tenant_id=tenant_id,
            actor_id=actor_id,
            project_id=row["project_id"],
            workspace_id=row["workspace_id"],
            input_ref=input_ref,
            key_id=key_id,
        )
        try:
            plaintext = AESGCM(key).decrypt(row["nonce"], row["ciphertext"], aad)
        except Exception as exc:
            raise WorkflowInputError("workflow_input_authentication_failed") from exc
        digest = hashlib.sha256(plaintext).hexdigest()
        if not secrets.compare_digest(digest, row["payload_digest"]):
            raise WorkflowInputError("workflow_input_digest_mismatch")
        try:
            value = json.loads(plaintext)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WorkflowInputError("workflow_input_payload_corrupt") from exc
        if not isinstance(value, dict):
            raise WorkflowInputError("workflow_input_payload_invalid")
        return value

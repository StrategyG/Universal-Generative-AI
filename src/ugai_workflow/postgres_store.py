"""Async PostgreSQL persistence with leases, fencing and optimistic transitions.

Pass an asyncpg-compatible Pool created by the hosting service. This module
does not create credentials, connect to a database, or expose a Data API route.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from .state_machine import CLAIMABLE_STATES, TaskState, validate_transition

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_:-]{0,79}$")
_SAFE_METADATA_KEYS = frozenset(
    {"request_ref", "source_ref", "context_ref", "schema_version", "correlation_id"}
)
_SAFE_EVENT_KEYS = frozenset(
    {
        "error_code",
        "evidence_digest",
        "decision_digest",
        "plan_digest",
        "test_reference",
        "verification_status",
        "attempt",
        "retry_delay_seconds",
    }
)


class WorkflowStoreError(RuntimeError):
    """Base persistence error."""


class TaskNotFound(WorkflowStoreError):
    """No task exists for the requested identifier."""


class IdempotencyConflict(WorkflowStoreError):
    """An idempotency key was reused with a different task identity or payload."""


class StaleWorkflowVersion(WorkflowStoreError):
    """The caller attempted to transition an outdated task snapshot."""


class LeaseLost(WorkflowStoreError):
    """The worker no longer owns a live lease for the task."""


@dataclass(frozen=True, slots=True)
class LeaseIdentity:
    worker_id: str
    lease_token: UUID


@dataclass(frozen=True, slots=True)
class WorkflowTask:
    task_id: UUID
    tenant_id: str
    actor_id: str
    task_type: str
    state: TaskState
    version: int
    retry_count: int
    max_retries: int
    retryable: bool
    idempotency_key: str
    input_digest: str
    priority: int
    available_at: datetime
    lease_owner: str | None
    lease_token: UUID | None
    lease_expires_at: datetime | None
    approval_reference: str | None
    decision_digest: str | None
    plan_digest: str | None
    error_code: str | None
    metadata: Mapping[str, Any]

    @classmethod
    def from_record(cls, row: Mapping[str, Any]) -> "WorkflowTask":
        raw_metadata = row["metadata"]
        if isinstance(raw_metadata, str):
            raw_metadata = json.loads(raw_metadata)
        return cls(
            task_id=row["task_id"],
            tenant_id=row["tenant_id"],
            actor_id=row["actor_id"],
            task_type=row["task_type"],
            state=TaskState(row["state"]),
            version=row["version"],
            retry_count=row["retry_count"],
            max_retries=row["max_retries"],
            retryable=row["retryable"],
            idempotency_key=row["idempotency_key"],
            input_digest=row["input_digest"],
            priority=row["priority"],
            available_at=row["available_at"],
            lease_owner=row["lease_owner"],
            lease_token=row["lease_token"],
            lease_expires_at=row["lease_expires_at"],
            approval_reference=row["approval_reference"],
            decision_digest=row["decision_digest"],
            plan_digest=row["plan_digest"],
            error_code=row["error_code"],
            metadata=raw_metadata or {},
        )


def canonical_json_digest(value: Mapping[str, Any]) -> str:
    """Return a stable digest for bounded JSON metadata, never hidden reasoning."""
    if not isinstance(value, Mapping):
        raise ValueError("json_value_must_be_object")
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("value_must_be_finite_json") from exc
    if len(encoded) > 64 * 1024:
        raise ValueError("json_value_too_large")
    return hashlib.sha256(encoded).hexdigest()


def _validate_text(name: str, value: str, max_length: int = 255) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise ValueError(f"{name}_invalid")


def _safe_metadata(value: Mapping[str, Any] | None) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("metadata_must_be_object")
    result: dict[str, str] = {}
    for key, item in value.items():
        if key not in _SAFE_METADATA_KEYS:
            raise ValueError("metadata_key_not_allowlisted")
        if not isinstance(item, str) or not item.strip() or len(item) > 255:
            raise ValueError("metadata_value_invalid")
        result[key] = item
    return result


def _safe_event_details(value: Mapping[str, Any] | None) -> dict[str, str | int | bool]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("event_metadata_must_be_object")
    result: dict[str, str | int | bool] = {}
    for key, item in value.items():
        if key not in _SAFE_EVENT_KEYS:
            raise ValueError("event_metadata_key_not_allowlisted")
        if isinstance(item, bool):
            result[key] = item
        elif isinstance(item, int) and 0 <= item <= 2**31 - 1:
            result[key] = item
        elif isinstance(item, str) and item.strip() and len(item) <= 255:
            result[key] = item
        else:
            raise ValueError("event_metadata_value_invalid")
    return result


class PostgresWorkflowStore:
    """Durable task store. All writes use parameterized SQL and DB transactions."""

    def __init__(self, pool: Any) -> None:
        if pool is None or not callable(getattr(pool, "acquire", None)):
            raise ValueError("async_postgres_pool_required")
        self._pool = pool

    async def create_task(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        task_type: str,
        idempotency_key: str,
        input_digest: str,
        priority: int = 0,
        max_retries: int = 2,
        metadata: Mapping[str, Any] | None = None,
    ) -> WorkflowTask:
        _validate_text("tenant_id", tenant_id, 128)
        _validate_text("actor_id", actor_id, 255)
        _validate_text("task_type", task_type, 128)
        if not _IDEMPOTENCY.fullmatch(idempotency_key or ""):
            raise ValueError("idempotency_key_invalid")
        if not _SHA256.fullmatch(input_digest or ""):
            raise ValueError("input_digest_must_be_sha256")
        if not isinstance(priority, int) or not -100 <= priority <= 100:
            raise ValueError("priority_out_of_bounds")
        if not isinstance(max_retries, int) or not 0 <= max_retries <= 2:
            raise ValueError("max_retries_must_be_between_0_and_2")

        safe_metadata = _safe_metadata(metadata)
        canonical_json_digest(safe_metadata)
        encoded_metadata = json.dumps(
            safe_metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )

        async with self._pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    INSERT INTO ugai_workflow.tasks (
                        tenant_id, actor_id, task_type, state, retry_count,
                        max_retries, retryable, idempotency_key, input_digest,
                        priority, metadata
                    )
                    VALUES ($1, $2, $3, 'received', 0, $4, false, $5, $6, $7, $8::jsonb)
                    ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
                    RETURNING *
                    """,
                    tenant_id, actor_id, task_type, max_retries,
                    idempotency_key, input_digest, priority, encoded_metadata,
                )
                if row is None:
                    row = await connection.fetchrow(
                        """
                        SELECT * FROM ugai_workflow.tasks
                        WHERE tenant_id = $1 AND idempotency_key = $2
                        FOR UPDATE
                        """,
                        tenant_id, idempotency_key,
                    )
                    if row is None:
                        raise WorkflowStoreError("idempotency_conflict_without_existing_task")
                    existing = WorkflowTask.from_record(row)
                    if (
                        existing.input_digest != input_digest
                        or existing.task_type != task_type
                        or existing.actor_id != actor_id
                        or existing.metadata != safe_metadata
                    ):
                        raise IdempotencyConflict("idempotency_key_payload_mismatch")
                    return existing

                task = WorkflowTask.from_record(row)
                await connection.execute(
                    """
                    INSERT INTO ugai_workflow.events (
                        task_id, task_version, actor_id, event_type,
                        from_state, to_state, details
                    )
                    VALUES ($1, $2, $3, 'task_created', NULL, 'received', $4::jsonb)
                    """,
                    task.task_id, task.version, actor_id,
                    json.dumps({"task_type": task_type, "input_digest": input_digest}),
                )
                return task

    async def get_task(self, task_id: UUID) -> WorkflowTask:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT * FROM ugai_workflow.tasks WHERE task_id = $1",
                task_id,
            )
        if row is None:
            raise TaskNotFound(str(task_id))
        return WorkflowTask.from_record(row)

    async def claim_next(
        self,
        *,
        worker_id: str,
        supported_task_types: Sequence[str],
        lease_seconds: int = 45,
    ) -> WorkflowTask | None:
        _validate_text("worker_id", worker_id, 128)
        if not supported_task_types or any(
            not isinstance(item, str) or not item.strip() for item in supported_task_types
        ):
            raise ValueError("supported_task_types_required")
        task_types = tuple(sorted(set(supported_task_types)))
        if not isinstance(lease_seconds, int) or not 5 <= lease_seconds <= 900:
            raise ValueError("lease_seconds_out_of_bounds")

        states = [state.value for state in CLAIMABLE_STATES]
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    WITH candidate AS (
                        SELECT task_id
                        FROM ugai_workflow.tasks
                        WHERE state = ANY($1::text[])
                          AND task_type = ANY($2::text[])
                          AND available_at <= clock_timestamp()
                          AND (
                              lease_token IS NULL
                              OR lease_expires_at <= clock_timestamp()
                          )
                        ORDER BY priority DESC, created_at ASC
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    UPDATE ugai_workflow.tasks AS task
                    SET lease_owner = $3,
                        lease_token = gen_random_uuid(),
                        lease_expires_at = clock_timestamp()
                            + make_interval(secs => $4),
                        updated_at = clock_timestamp()
                    FROM candidate
                    WHERE task.task_id = candidate.task_id
                    RETURNING task.*
                    """,
                    states, list(task_types), worker_id, lease_seconds,
                )
                if row is None:
                    return None
                task = WorkflowTask.from_record(row)
                await connection.execute(
                    """
                    INSERT INTO ugai_workflow.events (
                        task_id, task_version, actor_id, worker_id,
                        event_type, from_state, to_state, details
                    )
                    VALUES ($1, $2, $3, $4, 'lease_claimed', $5, $5, '{}'::jsonb)
                    """,
                    task.task_id, task.version, task.actor_id,
                    worker_id, task.state.value,
                )
                return task

    async def heartbeat(
        self,
        *,
        task_id: UUID,
        lease: LeaseIdentity,
        lease_seconds: int = 45,
    ) -> WorkflowTask:
        if not isinstance(lease_seconds, int) or not 5 <= lease_seconds <= 900:
            raise ValueError("lease_seconds_out_of_bounds")
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                UPDATE ugai_workflow.tasks
                SET lease_expires_at = clock_timestamp() + make_interval(secs => $4),
                    updated_at = clock_timestamp()
                WHERE task_id = $1
                  AND lease_owner = $2
                  AND lease_token = $3
                  AND lease_expires_at > clock_timestamp()
                RETURNING *
                """,
                task_id, lease.worker_id, lease.lease_token, lease_seconds,
            )
        if row is None:
            raise LeaseLost("lease_expired_or_fencing_token_mismatch")
        return WorkflowTask.from_record(row)

    async def transition(
        self,
        *,
        task_id: UUID,
        expected_version: int,
        target: TaskState,
        actor_id: str,
        reason_code: str,
        lease: LeaseIdentity | None = None,
        require_lease: bool = True,
        retryable: bool = False,
        approval_verified: bool = False,
        clarification_received: bool = False,
        operator_override: bool = False,
        retry_delay_seconds: int = 0,
        error_code: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> WorkflowTask:
        _validate_text("actor_id", actor_id, 255)
        if not _SAFE_CODE.fullmatch(reason_code or ""):
            raise ValueError("reason_code_invalid")
        if error_code is not None and not _SAFE_CODE.fullmatch(error_code):
            raise ValueError("error_code_invalid")
        if not isinstance(expected_version, int) or expected_version < 0:
            raise ValueError("expected_version_invalid")
        if not isinstance(retry_delay_seconds, int) or not 0 <= retry_delay_seconds <= 86_400:
            raise ValueError("retry_delay_seconds_out_of_bounds")

        event_details = _safe_event_details(metadata)
        event_details["reason_code"] = reason_code
        if error_code is not None:
            event_details["error_code"] = error_code
        event_json = json.dumps(
            event_details, sort_keys=True, separators=(",", ":"), allow_nan=False
        )

        async with self._pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    "SELECT * FROM ugai_workflow.tasks WHERE task_id = $1 FOR UPDATE",
                    task_id,
                )
                if row is None:
                    raise TaskNotFound(str(task_id))
                current = WorkflowTask.from_record(row)
                if current.version != expected_version:
                    raise StaleWorkflowVersion(
                        f"expected_version={expected_version}, actual_version={current.version}"
                    )

                if require_lease:
                    if lease is None:
                        raise LeaseLost("worker_transition_requires_lease")
                    if (
                        current.lease_owner != lease.worker_id
                        or current.lease_token != lease.lease_token
                        or current.lease_expires_at is None
                    ):
                        raise LeaseLost("worker_lease_identity_mismatch")
                    live = await connection.fetchval(
                        "SELECT $1::timestamptz > clock_timestamp()",
                        current.lease_expires_at,
                    )
                    if not live:
                        raise LeaseLost("worker_lease_expired")
                elif lease is not None:
                    raise ValueError("lease_not_allowed_for_unleased_transition")

                validate_transition(
                    current.state,
                    target,
                    retry_count=current.retry_count,
                    max_retries=current.max_retries,
                    retryable=current.retryable,
                    approval_verified=approval_verified,
                    clarification_received=clarification_received,
                    operator_override=operator_override,
                )

                retry_count = current.retry_count
                if current.state is TaskState.FAILED and target is TaskState.RECEIVED:
                    retry_count += 1
                stored_retryable = retryable if target is TaskState.FAILED else False

                updated = await connection.fetchrow(
                    """
                    UPDATE ugai_workflow.tasks
                    SET state = $2,
                        version = version + 1,
                        retry_count = $3,
                        retryable = $4,
                        error_code = CASE WHEN $2 = 'failed' THEN $5 ELSE NULL END,
                        available_at = CASE
                            WHEN $2 = 'received' AND $6 > 0
                                THEN clock_timestamp() + make_interval(secs => $6)
                            ELSE available_at
                        END,
                        lease_owner = NULL,
                        lease_token = NULL,
                        lease_expires_at = NULL,
                        updated_at = clock_timestamp()
                    WHERE task_id = $1 AND version = $7
                    RETURNING *
                    """,
                    task_id, target.value, retry_count, stored_retryable,
                    error_code, retry_delay_seconds, expected_version,
                )
                if updated is None:
                    raise StaleWorkflowVersion("task_changed_during_transition")

                new_task = WorkflowTask.from_record(updated)
                await connection.execute(
                    """
                    INSERT INTO ugai_workflow.events (
                        task_id, task_version, actor_id, worker_id,
                        event_type, from_state, to_state, details
                    )
                    VALUES ($1, $2, $3, $4, 'state_transition', $5, $6, $7::jsonb)
                    """,
                    task_id, new_task.version, actor_id,
                    lease.worker_id if lease else None,
                    current.state.value, target.value, event_json,
                )
                return new_task

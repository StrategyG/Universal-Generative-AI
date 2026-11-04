"""PostgreSQL-backed append-only decision audit sink."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from .workflow import DecisionAuditEvent


class _AsyncConnection(Protocol):
    async def fetchrow(self, query: str, *args: Any) -> Mapping[str, Any] | None:
        """Execute one parameterized query and return one row."""


class _AsyncAcquire(Protocol):
    async def __aenter__(self) -> _AsyncConnection: ...
    async def __aexit__(self, *args: object) -> None: ...


class _AsyncPool(Protocol):
    def acquire(self) -> _AsyncAcquire:
        """Acquire an asynchronous PostgreSQL connection."""


class PostgresDecisionAuditSink:
    """Persist redacted decision events using an asyncpg-compatible pool.

    The database role should have INSERT only on ugai_audit.decision_events.
    Event IDs are idempotent: an identical duplicate is accepted, while a
    duplicate ID with different content is rejected.
    """

    _MAX_DETAIL_ITEMS = 32
    _MAX_DETAIL_BYTES = 8_192

    def __init__(self, pool: _AsyncPool) -> None:
        if pool is None or not callable(getattr(pool, "acquire", None)):
            raise ValueError("async_postgres_pool_required")
        self._pool = pool

    async def append(self, event: DecisionAuditEvent) -> None:
        payload = self._serialize(event)
        async with self._pool.acquire() as connection:
            inserted = await connection.fetchrow(
                """
                INSERT INTO ugai_audit.decision_events (
                    event_id, workflow_id, decision_id, actor_id,
                    stage, outcome, occurred_at, details
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
                ON CONFLICT (event_id) DO NOTHING
                RETURNING event_id
                """,
                payload["event_id"],
                payload["workflow_id"],
                payload["decision_id"],
                payload["actor_id"],
                payload["stage"],
                payload["outcome"],
                payload["occurred_at"],
                json.dumps(
                    payload["details"],
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ),
            )
            if inserted is not None:
                return

            existing = await connection.fetchrow(
                """
                SELECT event_id, workflow_id, decision_id, actor_id,
                       stage, outcome, occurred_at, details
                FROM ugai_audit.decision_events
                WHERE event_id = $1
                """,
                payload["event_id"],
            )
            if existing is None or not self._same_event(existing, payload):
                raise RuntimeError("postgres_audit_event_id_conflict")

    @classmethod
    def _serialize(cls, event: DecisionAuditEvent) -> dict[str, Any]:
        if not isinstance(event, DecisionAuditEvent):
            raise TypeError("event_must_be_DecisionAuditEvent")

        limits = {
            "event_id": 128,
            "workflow_id": 128,
            "decision_id": 128,
            "actor_id": 255,
            "stage": 100,
            "outcome": 100,
        }
        required = {
            "event_id": event.event_id,
            "workflow_id": event.workflow_id,
            "decision_id": event.decision_id,
            "actor_id": event.actor_id,
            "stage": event.stage,
            "outcome": event.outcome,
        }
        for name, value in required.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError("audit_identity_and_classification_must_be_nonempty")
            if len(value) > limits[name]:
                raise ValueError(f"audit_{name}_too_long")

        try:
            occurred_at = datetime.fromisoformat(event.occurred_at)
        except (TypeError, ValueError) as exc:
            raise ValueError("audit_timestamp_must_be_iso8601") from exc
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError("audit_timestamp_requires_timezone")

        try:
            pairs = tuple(event.details)
            details = dict(pairs)
        except (TypeError, ValueError) as exc:
            raise ValueError("audit_details_must_be_key_value_pairs") from exc
        if len(details) != len(pairs):
            raise ValueError("audit_details_duplicate_keys")
        if len(details) > cls._MAX_DETAIL_ITEMS:
            raise ValueError("audit_details_too_many_entries")
        if any(
            not isinstance(key, str)
            or not key.strip()
            or len(key) > 80
            or not isinstance(value, str)
            or len(value) > 1_000
            for key, value in details.items()
        ):
            raise ValueError("audit_details_values_must_be_bounded_strings")

        encoded = json.dumps(
            details,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        if len(encoded) > cls._MAX_DETAIL_BYTES:
            raise ValueError("audit_details_exceed_encoded_size_limit")

        return {
            **required,
            "occurred_at": occurred_at.astimezone(UTC),
            "details": details,
        }

    @staticmethod
    def _same_event(existing: Mapping[str, Any], payload: Mapping[str, Any]) -> bool:
        existing_time = existing["occurred_at"]
        if isinstance(existing_time, str):
            existing_time = datetime.fromisoformat(existing_time)
        if existing_time.tzinfo is None:
            return False
        existing_details = existing["details"]
        if isinstance(existing_details, str):
            existing_details = json.loads(existing_details)
        return all(
            existing[key] == payload[key]
            for key in (
                "event_id",
                "workflow_id",
                "decision_id",
                "actor_id",
                "stage",
                "outcome",
            )
        ) and (
            existing_time.astimezone(UTC) == payload["occurred_at"]
            and existing_details == payload["details"]
        )

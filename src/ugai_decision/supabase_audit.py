"""Supabase RPC-backed durable sink for redacted UGAI decision audit events."""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from .workflow import DecisionAuditEvent


class _AsyncRPCBuilder(Protocol):
    def execute(self) -> Awaitable[Any]:
        """Execute one Supabase RPC asynchronously."""


class _AsyncSupabaseClient(Protocol):
    def rpc(self, function_name: str, params: Mapping[str, Any]) -> _AsyncRPCBuilder:
        """Build a Supabase RPC request."""


class SupabaseDecisionAuditSink:
    """Append events through a narrowly granted RPC into a private schema.

    Pass a server-side *async* Supabase client authenticated with a secret
    service identity. The underlying table schema is not exposed through
    PostgREST; only public.append_ugai_decision_event is exposed. Never
    construct this adapter in a browser or expose the secret key.
    """

    _RPC_NAME = "append_ugai_decision_event"
    _MAX_DETAIL_ITEMS = 32
    _MAX_DETAIL_BYTES = 8_192

    def __init__(self, client: _AsyncSupabaseClient) -> None:
        if client is None or not callable(getattr(client, "rpc", None)):
            raise ValueError("A configured server-side async Supabase client is required")
        self._client = client

    async def append(self, event: DecisionAuditEvent) -> None:
        payload = self._serialize(event)
        request = self._client.rpc(self._RPC_NAME, payload).execute()
        if not inspect.isawaitable(request):
            raise TypeError("SupabaseDecisionAuditSink requires an asynchronous Supabase client")
        result = await request
        error = getattr(result, "error", None)
        if error:
            raise RuntimeError("Supabase rejected the decision audit event") from error

    @classmethod
    def _serialize(cls, event: DecisionAuditEvent) -> dict[str, Any]:
        if not isinstance(event, DecisionAuditEvent):
            raise TypeError("event must be a DecisionAuditEvent")

        required = {
            "p_event_id": event.event_id,
            "p_workflow_id": event.workflow_id,
            "p_decision_id": event.decision_id,
            "p_actor_id": event.actor_id,
            "p_stage": event.stage,
            "p_outcome": event.outcome,
        }
        limits = {
            "p_event_id": 128,
            "p_workflow_id": 128,
            "p_decision_id": 128,
            "p_actor_id": 255,
            "p_stage": 100,
            "p_outcome": 100,
        }
        for name, value in required.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Audit event identity and classification fields must be non-empty strings")
            if len(value) > limits[name]:
                raise ValueError(f"{name} exceeds the database column limit")

        try:
            occurred_at = datetime.fromisoformat(event.occurred_at)
        except (TypeError, ValueError) as exc:
            raise ValueError("Audit event occurred_at must be an ISO-8601 timestamp") from exc
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError("Audit event occurred_at must include a timezone")

        try:
            detail_pairs = tuple(event.details)
            details = dict(detail_pairs)
        except (TypeError, ValueError) as exc:
            raise ValueError("Audit event details must be key/value pairs") from exc
        if len(details) != len(detail_pairs):
            raise ValueError("Audit event details must not contain duplicate keys")
        if len(details) > cls._MAX_DETAIL_ITEMS:
            raise ValueError("Audit event details contain too many entries")
        if any(
            not isinstance(key, str)
            or not key.strip()
            or len(key) > 80
            or not isinstance(value, str)
            or len(value) > 1_000
            for key, value in details.items()
        ):
            raise ValueError("Audit event details must contain bounded string keys and values")
        try:
            detail_size = len(
                json.dumps(details, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Audit event details must be JSON serializable") from exc
        if detail_size > cls._MAX_DETAIL_BYTES:
            raise ValueError("Audit event details exceed the maximum encoded size")

        return {
            **required,
            "p_occurred_at": occurred_at.astimezone(UTC).isoformat(),
            "p_details": details,
        }

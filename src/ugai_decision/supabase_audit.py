"""Supabase RPC-backed durable sink for redacted UGAI decision audit events."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from .workflow import DecisionAuditEvent


class SupabaseDecisionAuditSink:
    """Append events through a narrowly granted RPC into a private schema.

    Pass a server-side async Supabase client authenticated with a service
    identity. The underlying table schema is not exposed through PostgREST;
    only public.append_ugai_decision_event is exposed and executable by
    service_role. Never construct this adapter in a browser or expose keys.
    """

    _RPC_NAME = "append_ugai_decision_event"

    def __init__(self, client: Any) -> None:
        if client is None:
            raise ValueError("A configured server-side Supabase client is required")
        self._client = client

    async def append(self, event: DecisionAuditEvent) -> None:
        payload = self._serialize(event)
        result = self._client.rpc(self._RPC_NAME, payload).execute()
        if hasattr(result, "__await__"):
            result = await result
        error = getattr(result, "error", None)
        if error:
            raise RuntimeError("Supabase rejected the decision audit event") from error

    @staticmethod
    def _serialize(event: DecisionAuditEvent) -> dict[str, Any]:
        required = {
            "p_event_id": event.event_id,
            "p_workflow_id": event.workflow_id,
            "p_decision_id": event.decision_id,
            "p_actor_id": event.actor_id,
            "p_stage": event.stage,
            "p_outcome": event.outcome,
        }
        if any(not isinstance(value, str) or not value.strip() for value in required.values()):
            raise ValueError("Audit event identity and classification fields must be non-empty strings")
        try:
            occurred_at = datetime.fromisoformat(event.occurred_at.replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Audit event occurred_at must be an ISO-8601 timestamp") from exc
        if occurred_at.tzinfo is None:
            raise ValueError("Audit event occurred_at must include a timezone")

        details: Mapping[str, str] = dict(event.details)
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in details.items()):
            raise ValueError("Audit event details must contain string keys and values")

        return {
            **required,
            "p_occurred_at": occurred_at.isoformat(),
            "p_details": dict(details),
        }

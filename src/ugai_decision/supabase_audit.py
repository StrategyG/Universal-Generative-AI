"""Supabase-backed durable sink for redacted UGAI decision audit events."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from .workflow import DecisionAuditEvent


class SupabaseDecisionAuditSink:
    """Append decision events to a private Supabase schema.

    Pass a server-side Supabase client authenticated with a dedicated service
    identity. Never construct this adapter in a browser or expose service keys.
    The adapter intentionally supports the async Supabase client interface and
    does not own client creation, credentials, retries, or connection lifecycle.
    """

    def __init__(self, client: Any, *, schema: str = "ugai_audit") -> None:
        if client is None:
            raise ValueError("A configured server-side Supabase client is required")
        if schema != "ugai_audit":
            raise ValueError("The decision audit sink is pinned to the private ugai_audit schema")
        self._client = client
        self._schema = schema

    async def append(self, event: DecisionAuditEvent) -> None:
        payload = self._serialize(event)
        query = (
            self._client.schema(self._schema)
            .table("decision_events")
            .insert(payload)
        )
        result = query.execute()
        if hasattr(result, "__await__"):
            result = await result
        error = getattr(result, "error", None)
        if error:
            raise RuntimeError("Supabase rejected the decision audit event") from error

    @staticmethod
    def _serialize(event: DecisionAuditEvent) -> dict[str, Any]:
        required = {
            "event_id": event.event_id,
            "workflow_id": event.workflow_id,
            "decision_id": event.decision_id,
            "actor_id": event.actor_id,
            "stage": event.stage,
            "outcome": event.outcome,
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
            "occurred_at": occurred_at.isoformat(),
            "details": dict(details),
        }

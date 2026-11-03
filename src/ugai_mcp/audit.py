"""Secret-free audit contract for UGAI-to-IM19 tool execution.

Implement AuditSink with a durable, access-controlled store. Events deliberately
exclude bearer tokens, OAuth material, tool arguments, and provider result bodies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol


@dataclass(frozen=True, slots=True)
class MCPAuditEvent:
    request_id: str
    actor_id: str
    tool_name: str
    outcome: str
    occurred_at: str
    duration_ms: int
    error_code: str | None = None


class AuditSink(Protocol):
    async def write(self, event: MCPAuditEvent) -> None:
        """Durably persist a redacted event or raise an exception."""


def make_audit_event(
    *,
    request_id: str,
    actor_id: str,
    tool_name: str,
    outcome: str,
    duration_ms: int,
    error_code: str | None = None,
) -> MCPAuditEvent:
    return MCPAuditEvent(
        request_id=request_id,
        actor_id=actor_id,
        tool_name=tool_name,
        outcome=outcome,
        occurred_at=datetime.now(timezone.utc).isoformat(),
        duration_ms=max(0, duration_ms),
        error_code=error_code,
    )

"""Default-deny MCP tool policy with an operator-reviewed allowlist.

IM19 0.3 currently registers tools without MCP read-only annotations. Therefore,
the explicit UGAI allowlist is the authoritative operator approval. If the server
does supply safety annotations, contradictory or destructive annotations deny access.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


_MISSING = object()


@dataclass(frozen=True, slots=True)
class ToolDecision:
    allowed: bool
    reason: str


def _get(value: Any, key: str, default: Any = None) -> Any:
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


class ToolPolicy:
    def __init__(self, allowed_tools: Iterable[str] = ()) -> None:
        self.allowed = frozenset(x for x in allowed_tools if x)

    def evaluate(self, tool: Any) -> ToolDecision:
        name = _get(tool, "name", "")
        if not isinstance(name, str) or not name:
            return ToolDecision(False, "invalid_name")
        if name not in self.allowed:
            return ToolDecision(False, "not_allowlisted")

        annotations = _get(tool, "annotations", {}) or {}
        read_only = _get(annotations, "readOnlyHint", _MISSING)
        destructive = _get(annotations, "destructiveHint", _MISSING)
        if read_only is not _MISSING and read_only is not True:
            return ToolDecision(False, "server_marks_tool_not_read_only")
        if destructive is not _MISSING and destructive is not False:
            return ToolDecision(False, "server_marks_tool_destructive")

        schema = _get(tool, "inputSchema", {}) or {}
        if _get(schema, "type") != "object":
            return ToolDecision(False, "invalid_schema")
        return ToolDecision(True, "operator_allowlisted")

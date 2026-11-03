"""Default-deny MCP tool policy."""
from dataclasses import dataclass
from typing import Any, Iterable


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
        if _get(annotations, "readOnlyHint", False) is not True:
            return ToolDecision(False, "not_read_only")
        if _get(annotations, "destructiveHint", True) is not False:
            return ToolDecision(False, "destructive_or_unattested")
        schema = _get(tool, "inputSchema", {}) or {}
        if _get(schema, "type") != "object":
            return ToolDecision(False, "invalid_schema")
        return ToolDecision(True, "allowlisted_read_only")

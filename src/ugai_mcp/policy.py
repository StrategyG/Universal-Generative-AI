"""Default-deny MCP tool policy with an operator-reviewed allowlist."""

_MISSING = object()

# Never expose these identity, content, write, or approval-control tools to a
# general-purpose UGAI agent, even if an allowlist is misconfigured.
_DENIED_TOOL_NAMES = frozenset(
    {
        "request_service_authorization",
        "confirm_service_authorization",
        "disconnect_service",
        "drive_read_file",
        "drive_create_folder",
        "drive_get_write_approval_status",
        "cloudbrowser_get_task",
        "cloudbrowser_list_tasks",
    }
)


class ToolDecision:
    __slots__ = ("allowed", "reason")

    def __init__(self, allowed: bool, reason: str) -> None:
        self.allowed = allowed
        self.reason = reason


def _get(value, key: str, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def _field(value, snake_name: str, camel_name: str, default=None):
    snake = _get(value, snake_name, _MISSING)
    if snake is not _MISSING:
        return snake
    return _get(value, camel_name, default)


class ToolPolicy:
    def __init__(self, allowed_tools=()) -> None:
        if isinstance(allowed_tools, (str, bytes)) or not isinstance(
            allowed_tools, (set, frozenset, list, tuple)
        ):
            raise TypeError("Tool allowlist must be a collection of names")
        if any(not isinstance(name, str) or not name for name in allowed_tools):
            raise ValueError("Tool allowlist contains an invalid name")
        self.allowed = frozenset(allowed_tools)

    def evaluate(self, tool) -> ToolDecision:
        name = _get(tool, "name", "")
        if not isinstance(name, str) or not name:
            return ToolDecision(False, "invalid_name")
        unqualified_name = name.rsplit("__", 1)[-1]
        if name in _DENIED_TOOL_NAMES or unqualified_name in _DENIED_TOOL_NAMES:
            return ToolDecision(False, "hard_denied_tool")
        if name not in self.allowed:
            return ToolDecision(False, "not_allowlisted")

        annotations = _get(tool, "annotations", {}) or {}
        # SDK 2.x exposes snake_case model fields. Keep camelCase compatibility
        # for raw dictionaries and older providers. None means "not supplied";
        # the operator allowlist remains the admission authority for such tools.
        read_only = _field(annotations, "read_only_hint", "readOnlyHint", _MISSING)
        destructive = _field(annotations, "destructive_hint", "destructiveHint", _MISSING)
        if read_only is False or (
            read_only is not None and read_only is not _MISSING and read_only is not True
        ):
            return ToolDecision(False, "server_marks_tool_not_read_only")
        if destructive is True or (
            destructive is not None
            and destructive is not _MISSING
            and destructive is not False
        ):
            return ToolDecision(False, "server_marks_tool_destructive")

        schema = _field(tool, "input_schema", "inputSchema", {}) or {}
        if _get(schema, "type") != "object":
            return ToolDecision(False, "invalid_schema")
        return ToolDecision(True, "operator_allowlisted")

from types import SimpleNamespace

from ugai_mcp.policy import ToolPolicy


def test_policy_rejects_missing_and_non_string_names():
    policy = ToolPolicy({"drive_search_files"})
    assert policy.evaluate({}).reason == "invalid_name"
    assert policy.evaluate({"name": ""}).reason == "invalid_name"
    assert policy.evaluate({"name": 42}).reason == "invalid_name"


def test_policy_supports_dictionary_and_object_tool_metadata():
    policy = ToolPolicy({"drive_search_files", "youtube_get_channel"})
    dictionary_tool = {
        "name": "drive_search_files",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {"type": "object"},
    }
    object_tool = SimpleNamespace(
        name="youtube_get_channel",
        annotations=SimpleNamespace(readOnlyHint=True, destructiveHint=False),
        inputSchema=SimpleNamespace(type="object"),
    )
    assert policy.evaluate(dictionary_tool).allowed is True
    assert policy.evaluate(object_tool).allowed is True


def test_policy_rejects_malformed_annotation_and_schema_shapes():
    policy = ToolPolicy({"drive_search_files"})
    assert policy.evaluate({
        "name": "drive_search_files",
        "annotations": {"readOnlyHint": None},
        "inputSchema": {"type": "object"},
    }).reason == "server_marks_tool_not_read_only"
    assert policy.evaluate({
        "name": "drive_search_files",
        "annotations": {"destructiveHint": True},
        "inputSchema": {"type": "object"},
    }).reason == "server_marks_tool_destructive"
    assert policy.evaluate({
        "name": "drive_search_files",
        "annotations": {},
        "inputSchema": {},
    }).reason == "invalid_schema"

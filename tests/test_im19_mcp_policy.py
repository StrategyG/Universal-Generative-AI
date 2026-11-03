from types import SimpleNamespace

from ugai_mcp.policy import ToolPolicy


def tool(name="drive_search_files", read_only=True, destructive=False, schema_type="object"):
    return SimpleNamespace(
        name=name,
        annotations=SimpleNamespace(
            readOnlyHint=read_only,
            destructiveHint=destructive,
        ),
        inputSchema={"type": schema_type},
    )


def test_allowlisted_read_only_tool_is_approved():
    decision = ToolPolicy({"drive_search_files"}).evaluate(tool())
    assert decision.allowed is True


def test_default_deny_when_not_allowlisted():
    decision = ToolPolicy().evaluate(tool())
    assert decision.allowed is False
    assert decision.reason == "not_allowlisted"


def test_server_annotations_can_deny_tool():
    policy = ToolPolicy({"drive_search_files", "drive_create_folder"})
    assert not policy.evaluate(tool("drive_create_folder", True, True)).allowed
    assert not policy.evaluate(tool("drive_search_files", False, False)).allowed


def test_non_object_schema_is_denied():
    decision = ToolPolicy({"drive_search_files"}).evaluate(tool(schema_type="string"))
    assert decision.allowed is False


def test_allowlisted_im19_tool_without_annotations_is_supported():
    im19_tool = SimpleNamespace(
        name="youtube_get_channel",
        inputSchema={"type": "object"},
    )
    decision = ToolPolicy({"youtube_get_channel"}).evaluate(im19_tool)
    assert decision.allowed is True
    assert decision.reason == "operator_allowlisted"


def test_high_risk_tools_are_hard_denied_even_if_allowlisted():
    dangerous = {
        "request_service_authorization",
        "confirm_service_authorization",
        "disconnect_service",
        "drive_read_file",
        "drive_create_folder",
        "cloudbrowser_get_task",
        "cloudbrowser_list_tasks",
    }
    policy = ToolPolicy(dangerous)
    for name in dangerous:
        assert policy.evaluate(tool(name)).reason == "hard_denied_tool"

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


def test_privileged_tools_are_hard_denied_even_if_allowlisted():
    dangerous = {
        "request_service_authorization",
        "confirm_service_authorization",
        "disconnect_service",
        "drive_read_file",
        "drive_create_folder",
        "drive_get_write_approval_status",
        "cloudbrowser_get_task",
        "cloudbrowser_list_tasks",
    }
    policy = ToolPolicy(dangerous)
    for name in dangerous:
        assert policy.evaluate(tool(name)).reason == "hard_denied_tool"



def test_mcp_sdk_v2_snake_case_fields_with_optional_annotations():
    sdk_tool = SimpleNamespace(
        name="youtube_get_channel",
        annotations=SimpleNamespace(read_only_hint=None, destructive_hint=None),
        input_schema={"type": "object"},
    )
    decision = ToolPolicy({"youtube_get_channel"}).evaluate(sdk_tool)
    assert decision.allowed is True


def test_mcp_sdk_v2_explicit_mutating_annotations_are_denied():
    policy = ToolPolicy({"drive_create_folder", "unsafe_mutation"})
    assert not policy.evaluate(SimpleNamespace(
        name="drive_create_folder",
        annotations=SimpleNamespace(read_only_hint=False, destructive_hint=False),
        input_schema={"type": "object"},
    )).allowed
    assert not policy.evaluate(SimpleNamespace(
        name="unsafe_mutation",
        annotations=SimpleNamespace(read_only_hint=None, destructive_hint=True),
        input_schema={"type": "object"},
    )).allowed


def test_mcp_sdk_v2_malformed_schema_is_denied():
    decision = ToolPolicy({"bad_schema"}).evaluate(SimpleNamespace(
        name="bad_schema",
        annotations=None,
        input_schema={"type": "string"},
    ))
    assert decision.allowed is False
    assert decision.reason == "invalid_schema"



def test_mcp_sdk_2_streamable_http_transport_contract():
    import inspect

    from mcp.client.streamable_http import streamable_http_client

    parameters = inspect.signature(streamable_http_client).parameters
    assert "http_client" in parameters
    assert "max_sse_event_size" in parameters
    assert "headers" not in parameters

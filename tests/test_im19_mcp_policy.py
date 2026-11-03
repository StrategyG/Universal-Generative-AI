from types import SimpleNamespace

from ugai_mcp.policy import ToolPolicy


def tool(name="drive_search", read_only=True, destructive=False, schema_type="object"):
    return SimpleNamespace(
        name=name,
        annotations=SimpleNamespace(
            readOnlyHint=read_only,
            destructiveHint=destructive,
        ),
        inputSchema={"type": schema_type},
    )


def test_allowlisted_read_only_tool_is_approved():
    decision = ToolPolicy({"drive_search"}).evaluate(tool())
    assert decision.allowed is True


def test_default_deny_when_not_allowlisted():
    decision = ToolPolicy().evaluate(tool())
    assert decision.allowed is False
    assert decision.reason == "not_allowlisted"


def test_write_or_unattested_tool_is_denied():
    policy = ToolPolicy({"drive_search", "drive_create_folder"})
    assert not policy.evaluate(tool("drive_create_folder", True, True)).allowed
    assert not policy.evaluate(tool("drive_search", False, False)).allowed


def test_non_object_schema_is_denied():
    decision = ToolPolicy({"drive_search"}).evaluate(tool(schema_type="string"))
    assert decision.allowed is False

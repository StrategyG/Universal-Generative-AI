from types import SimpleNamespace

import pytest

from ugai_mcp.audit import MCPAuditEvent
from ugai_mcp.client import AuditUnavailable, IM19MCPClient
from ugai_mcp.config import IM19Config


class TokenProvider:
    async def get_access_token(self, *, resource: str) -> str:
        return "short-lived-test-token"


class RecordingAudit:
    def __init__(self, fail_on_call=None):
        self.events = []
        self.calls = 0
        self.fail_on_call = fail_on_call

    async def write(self, event: MCPAuditEvent) -> None:
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise OSError("audit store unavailable")
        self.events.append(event)


class FakeSession:
    def __init__(self, result=None):
        self.result = result or SimpleNamespace(isError=False, content=[{"text": "ok"}])
        self.calls = 0

    async def call_tool(self, name, arguments):
        self.calls += 1
        return self.result


def make_client(audit):
    config = IM19Config(
        endpoint="https://im19.example/mcp",
        resource="https://im19.example",
        allowed_tools=frozenset({"youtube_get_channel"}),
    )
    client = IM19MCPClient(
        config=config,
        token_provider=TokenProvider(),
        audit_sink=audit,
        actor_id="authenticated-user-123",
    )
    client._session = FakeSession()
    client._tools = {"youtube_get_channel": object()}
    return client


@pytest.mark.asyncio
async def test_tool_call_is_audited_without_arguments_or_result_body():
    audit = RecordingAudit()
    client = make_client(audit)
    result = await client.call_tool("youtube_get_channel", {"private": "sensitive-value"})

    assert result["status"] == "success"
    assert len(audit.events) == 2
    assert [event.outcome for event in audit.events] == ["STARTED", "SUCCEEDED"]
    assert all(not hasattr(event, "arguments") for event in audit.events)
    assert all(not hasattr(event, "result") for event in audit.events)
    assert all(event.actor_id == "authenticated-user-123" for event in audit.events)


@pytest.mark.asyncio
async def test_audit_start_failure_prevents_remote_execution():
    audit = RecordingAudit(fail_on_call=1)
    client = make_client(audit)

    with pytest.raises(AuditUnavailable) as error:
        await client.call_tool("youtube_get_channel", {"x": "y"})

    assert error.value.execution_may_have_completed is False
    assert client._session.calls == 0


@pytest.mark.asyncio
async def test_audit_completion_failure_reports_uncertain_execution():
    audit = RecordingAudit(fail_on_call=2)
    client = make_client(audit)

    with pytest.raises(AuditUnavailable) as error:
        await client.call_tool("youtube_get_channel", {})

    assert error.value.execution_may_have_completed is True
    assert client._session.calls == 1


def test_runtime_requires_trusted_actor_identity():
    from ugai_mcp.runtime import IM19ToolProvider

    config = IM19Config(
        endpoint="https://im19.example/mcp",
        resource="https://im19.example",
        allowed_tools=frozenset(),
    )
    with pytest.raises(ValueError):
        IM19ToolProvider(
            config=config,
            token_provider=TokenProvider(),
            audit_sink=RecordingAudit(),
            actor_id="",
        )

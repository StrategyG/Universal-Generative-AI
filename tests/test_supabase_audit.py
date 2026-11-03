from dataclasses import replace
from datetime import UTC, datetime

import pytest

from ugai_decision.supabase_audit import SupabaseDecisionAuditSink
from ugai_decision.workflow import DecisionAuditEvent


class FakeResponse:
    error = None


class FakeRPC:
    def __init__(self, calls, name, params):
        self.calls = calls
        self.name = name
        self.params = params

    async def execute(self):
        self.calls.append((self.name, self.params))
        return FakeResponse()


class FakeSupabase:
    def __init__(self):
        self.calls = []

    def rpc(self, name, params):
        return FakeRPC(self.calls, name, params)


def sample_event():
    return DecisionAuditEvent(
        event_id="evt-001",
        workflow_id="workflow-001",
        decision_id="decision-001",
        actor_id="actor-001",
        stage="workflow_started",
        outcome="accepted",
        occurred_at=datetime.now(UTC).isoformat(),
        details=(("source_count", "3"),),
    )


@pytest.mark.asyncio
async def test_supabase_sink_persists_redacted_event_through_narrow_rpc() -> None:
    client = FakeSupabase()
    sink = SupabaseDecisionAuditSink(client)

    await sink.append(sample_event())

    assert len(client.calls) == 1
    name, payload = client.calls[0]
    assert name == "append_ugai_decision_event"
    assert payload["p_event_id"] == "evt-001"
    assert payload["p_details"] == {"source_count": "3"}


@pytest.mark.asyncio
async def test_supabase_sink_rejects_naive_timestamp_before_write() -> None:
    client = FakeSupabase()
    sink = SupabaseDecisionAuditSink(client)
    event = replace(sample_event(), occurred_at="2026-11-04T12:00:00")

    with pytest.raises(ValueError, match="timezone"):
        await sink.append(event)

    assert client.calls == []

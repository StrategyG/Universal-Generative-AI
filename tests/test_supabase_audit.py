from datetime import UTC, datetime

import pytest

from ugai_decision.supabase_audit import SupabaseDecisionAuditSink
from ugai_decision.workflow import DecisionAuditEvent


class FakeResponse:
    error = None


class FakeQuery:
    def __init__(self, calls):
        self.calls = calls
        self.payload = None

    def insert(self, payload):
        self.payload = payload
        return self

    async def execute(self):
        self.calls.append(self.payload)
        return FakeResponse()


class FakeSchema:
    def __init__(self, calls):
        self.calls = calls

    def table(self, name):
        assert name == "decision_events"
        return FakeQuery(self.calls)


class FakeSupabase:
    def __init__(self):
        self.calls = []

    def schema(self, name):
        assert name == "ugai_audit"
        return FakeSchema(self.calls)


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
async def test_supabase_sink_persists_redacted_event() -> None:
    client = FakeSupabase()
    sink = SupabaseDecisionAuditSink(client)

    await sink.append(sample_event())

    assert len(client.calls) == 1
    assert client.calls[0]["event_id"] == "evt-001"
    assert client.calls[0]["details"] == {"source_count": "3"}


def test_supabase_sink_rejects_public_or_unexpected_schema() -> None:
    with pytest.raises(ValueError, match="pinned"):
        SupabaseDecisionAuditSink(FakeSupabase(), schema="public")


@pytest.mark.asyncio
async def test_supabase_sink_rejects_naive_timestamp_before_write() -> None:
    client = FakeSupabase()
    sink = SupabaseDecisionAuditSink(client)
    event = sample_event()
    event = DecisionAuditEvent(
        **{**event.__dict__, "occurred_at": "2026-11-04T12:00:00"}
    )

    with pytest.raises(ValueError, match="timezone"):
        await sink.append(event)

    assert client.calls == []

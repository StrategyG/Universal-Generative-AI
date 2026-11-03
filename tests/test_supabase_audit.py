from dataclasses import replace
from datetime import UTC, datetime

import pytest

from ugai_decision.supabase_audit import SupabaseDecisionAuditSink
from ugai_decision.workflow import DecisionAuditEvent


class FakeResponse:
    def __init__(self, error=None):
        self.error = error


class FakeRPC:
    def __init__(self, calls, name, params, error=None):
        self.calls = calls
        self.name = name
        self.params = params
        self.error = error

    async def execute(self):
        self.calls.append((self.name, self.params))
        return FakeResponse(self.error)


class FakeSupabase:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def rpc(self, name, params):
        return FakeRPC(self.calls, name, params, self.error)


class SyncRPC:
    def execute(self):
        return FakeResponse()


class SyncSupabase:
    def rpc(self, name, params):
        return SyncRPC()


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
async def test_supabase_sink_normalizes_timestamp_to_utc() -> None:
    client = FakeSupabase()
    sink = SupabaseDecisionAuditSink(client)
    event = replace(sample_event(), occurred_at="2026-11-04T12:00:00+07:00")

    await sink.append(event)

    assert client.calls[0][1]["p_occurred_at"] == "2026-11-04T05:00:00+00:00"


@pytest.mark.asyncio
async def test_supabase_sink_rejects_naive_timestamp_before_write() -> None:
    client = FakeSupabase()
    sink = SupabaseDecisionAuditSink(client)
    event = replace(sample_event(), occurred_at="2026-11-04T12:00:00")

    with pytest.raises(ValueError, match="timezone"):
        await sink.append(event)

    assert client.calls == []


@pytest.mark.asyncio
async def test_supabase_sink_rejects_duplicate_detail_keys() -> None:
    client = FakeSupabase()
    sink = SupabaseDecisionAuditSink(client)
    event = replace(sample_event(), details=(("stage", "first"), ("stage", "second")))

    with pytest.raises(ValueError, match="duplicate"):
        await sink.append(event)

    assert client.calls == []


@pytest.mark.asyncio
async def test_supabase_sink_rejects_oversized_aggregate_details() -> None:
    client = FakeSupabase()
    sink = SupabaseDecisionAuditSink(client)
    details = tuple((f"field_{index}", "x" * 950) for index in range(9))
    event = replace(sample_event(), details=details)

    with pytest.raises(ValueError, match="maximum encoded size"):
        await sink.append(event)

    assert client.calls == []


@pytest.mark.asyncio
async def test_supabase_sink_rejects_too_many_detail_items() -> None:
    client = FakeSupabase()
    sink = SupabaseDecisionAuditSink(client)
    details = tuple((f"field_{index}", "ok") for index in range(33))
    event = replace(sample_event(), details=details)

    with pytest.raises(ValueError, match="too many entries"):
        await sink.append(event)

    assert client.calls == []


@pytest.mark.asyncio
async def test_supabase_sink_requires_async_client_to_avoid_blocking_workflow() -> None:
    sink = SupabaseDecisionAuditSink(SyncSupabase())

    with pytest.raises(TypeError, match="asynchronous"):
        await sink.append(sample_event())


@pytest.mark.asyncio
async def test_supabase_sink_propagates_database_rejection() -> None:
    sink = SupabaseDecisionAuditSink(FakeSupabase(error=RuntimeError("denied")))

    with pytest.raises(RuntimeError, match="rejected"):
        await sink.append(sample_event())

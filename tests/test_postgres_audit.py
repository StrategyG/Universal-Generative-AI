from dataclasses import replace
from datetime import UTC, datetime

import pytest

from ugai_decision.postgres_audit import PostgresDecisionAuditSink
from ugai_decision.workflow import DecisionAuditEvent


class FakeConnection:
    def __init__(self):
        self.inserted = {}
        self.calls = []

    async def fetchrow(self, query, *args):
        self.calls.append((query, args))
        if query.lstrip().startswith("INSERT"):
            if self.inserted:
                # Simulate INSERT ... ON CONFLICT DO NOTHING.
                return None
            self.inserted = {
                "event_id": args[0],
                "workflow_id": args[1],
                "decision_id": args[2],
                "actor_id": args[3],
                "stage": args[4],
                "outcome": args[5],
                "occurred_at": args[6],
                "details": args[7],
            }
            return {"event_id": args[0]}
        return self.inserted or None


class FakeAcquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *_args):
        return None


class FakePool:
    def __init__(self):
        self.connection = FakeConnection()

    def acquire(self):
        return FakeAcquire(self.connection)


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
async def test_postgres_sink_inserts_redacted_event_with_parameters():
    pool = FakePool()
    await PostgresDecisionAuditSink(pool).append(sample_event())

    query, args = pool.connection.calls[0]
    assert "INSERT INTO ugai_audit.decision_events" in query
    assert args[:6] == (
        "evt-001",
        "workflow-001",
        "decision-001",
        "actor-001",
        "workflow_started",
        "accepted",
    )
    assert '"source_count":"3"' in args[7]


@pytest.mark.asyncio
async def test_postgres_sink_normalizes_timestamps_to_utc():
    pool = FakePool()
    event = replace(sample_event(), occurred_at="2026-11-04T12:00:00+07:00")

    await PostgresDecisionAuditSink(pool).append(event)

    assert pool.connection.calls[0][1][6].isoformat() == "2026-11-04T05:00:00+00:00"


@pytest.mark.asyncio
async def test_postgres_sink_rejects_naive_timestamps_before_writing():
    pool = FakePool()
    event = replace(sample_event(), occurred_at="2026-11-04T12:00:00")

    with pytest.raises(ValueError, match="timezone"):
        await PostgresDecisionAuditSink(pool).append(event)

    assert pool.connection.calls == []


@pytest.mark.asyncio
async def test_postgres_sink_rejects_duplicate_detail_keys():
    pool = FakePool()
    event = replace(sample_event(), details=(("stage", "first"), ("stage", "second")))

    with pytest.raises(ValueError, match="duplicate"):
        await PostgresDecisionAuditSink(pool).append(event)

    assert pool.connection.calls == []


@pytest.mark.asyncio
async def test_postgres_sink_rejects_oversized_details():
    pool = FakePool()
    details = tuple((f"field_{index}", "x" * 950) for index in range(9))
    event = replace(sample_event(), details=details)

    with pytest.raises(ValueError, match="encoded_size"):
        await PostgresDecisionAuditSink(pool).append(event)

    assert pool.connection.calls == []


@pytest.mark.asyncio
async def test_postgres_sink_rejects_duplicate_event_id_with_different_content():
    pool = FakePool()
    sink = PostgresDecisionAuditSink(pool)
    existing = replace(sample_event(), outcome="old")
    await sink.append(existing)
    pool.connection.calls.clear()

    with pytest.raises(RuntimeError, match="event_id_conflict"):
        await sink.append(sample_event())

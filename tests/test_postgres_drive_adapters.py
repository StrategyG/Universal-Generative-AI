from __future__ import annotations

from datetime import UTC
import pytest

from ugai_decision.postgres_drive import (
    DriveEvidenceReceipt, PostgresDecisionAuditSink, PostgresEvidenceRegistry,
)
from ugai_decision.workflow import DecisionAuditEvent


class Acquire:
    def __init__(self, conn): self.conn = conn
    async def __aenter__(self): return self.conn
    async def __aexit__(self, *args): return None


class FakePool:
    def __init__(self): self.calls = []
    def acquire(self): return Acquire(self)
    async def execute(self, *args): self.calls.append(args)


@pytest.mark.asyncio
async def test_postgres_audit_sink_persists_event():
    pool = FakePool()
    event = DecisionAuditEvent(
        "evt-1", "wf-1", "dec-1", "actor-1", "evaluated", "hold",
        "2026-11-04T12:00:00Z", (("reason", "insufficient_evidence"),),
    )
    await PostgresDecisionAuditSink(pool=pool).append(event)
    assert len(pool.calls) == 1
    assert pool.calls[0][1:6] == ("evt-1", "wf-1", "dec-1", "actor-1", "evaluated")
    assert pool.calls[0][7].tzinfo == UTC


@pytest.mark.asyncio
async def test_audit_sink_rejects_naive_timestamp():
    pool = FakePool()
    event = DecisionAuditEvent("e", "w", "d", "a", "s", "o", "2026-11-04T12:00:00", ())
    with pytest.raises(ValueError, match="timezone"):
        await PostgresDecisionAuditSink(pool=pool).append(event)


@pytest.mark.asyncio
async def test_registry_rejects_invalid_hash():
    registry = PostgresEvidenceRegistry(pool=FakePool())
    receipt = DriveEvidenceReceipt("drive-id", "proof.pdf", "application/pdf", "bad", 20, None)
    with pytest.raises(ValueError, match="SHA-256"):
        await registry.register(evidence_id="e1", actor_id="a1", receipt=receipt)

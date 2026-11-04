import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ugai_workflow.postgres_store import LeaseLost
from ugai_workflow.state_machine import TaskState
from ugai_workflow.worker import HybridWorker, WorkerRegistration, WorkerTier


class DatabaseDriverFailure(Exception):
    """Simulate a driver exception outside the worker's built-in error classes."""


class FailingHeartbeatStore:
    def __init__(self) -> None:
        self.transition_calls: list[dict] = []

    async def claim_next(self, **kwargs):
        return SimpleNamespace(
            task_id=uuid4(),
            version=1,
            lease_token=uuid4(),
            actor_id="trusted-actor",
            tenant_id="tenant-001",
            task_type="long_running",
        )

    async def heartbeat(self, **kwargs):
        raise DatabaseDriverFailure("connection lost")

    async def transition(self, **kwargs):
        self.transition_calls.append(kwargs)


class BlockingHandler:
    def __init__(self) -> None:
        self.cancelled = asyncio.Event()

    async def handle(self, task):
        try:
            await asyncio.Event().wait()
        finally:
            self.cancelled.set()


@pytest.mark.asyncio
async def test_unexpected_heartbeat_failure_cancels_handler_and_fails_closed() -> None:
    store = FailingHeartbeatStore()
    handler = BlockingHandler()
    worker = HybridWorker(
        store=store,
        registration=WorkerRegistration(
            worker_id="worker-1",
            tier=WorkerTier.DEDICATED,
            tenant_id="tenant-001",
            task_types=("long_running",),
            lease_seconds=6,
            heartbeat_seconds=1,
        ),
        handlers={"long_running": handler},
    )

    with pytest.raises(LeaseLost, match="worker_lost_lease"):
        await asyncio.wait_for(worker.run_once(), timeout=3)

    assert handler.cancelled.is_set()
    assert store.transition_calls == []


def test_worker_registration_rejects_untrusted_runtime_types() -> None:
    invalid_tier = WorkerRegistration(
        worker_id="worker-1",
        tier="dedicated",
        tenant_id="tenant-001",
        task_types=("long_running",),
    )
    with pytest.raises(ValueError, match="worker_tier_invalid"):
        invalid_tier.validate()

    invalid_lease = WorkerRegistration(
        worker_id="worker-1",
        tier=WorkerTier.DEDICATED,
        tenant_id="tenant-001",
        task_types=("long_running",),
        lease_seconds=True,
    )
    with pytest.raises(ValueError, match="lease_seconds_out_of_bounds"):
        invalid_lease.validate()


def test_worker_outcome_rejects_non_enum_state() -> None:
    from ugai_workflow.worker import WorkerOutcome

    outcome = WorkerOutcome(next_state="succeeded", reason_code="completed")
    with pytest.raises(ValueError, match="worker_next_state_invalid"):
        outcome.validate()

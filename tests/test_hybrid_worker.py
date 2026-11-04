import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ugai_workflow.postgres_store import LeaseLost
from ugai_workflow.state_machine import TaskState
from ugai_workflow.worker import (
    ExternalOutcomeUnknown,
    HybridWorker,
    RetryScheduler,
    RetrySchedulerRegistration,
    WorkerOutcome,
    WorkerRegistration,
    WorkerTier,
)


class FakeStore:
    def __init__(self, task):
        self.task = task
        self.transition_calls = []
        self.heartbeat_calls = []

    async def claim_next(self, **kwargs):
        return self.task

    async def transition(self, **kwargs):
        self.transition_calls.append(kwargs)
        return self.task

    async def heartbeat(self, **kwargs):
        self.heartbeat_calls.append(kwargs)
        return self.task


class GoodHandler:
    async def handle(self, task):
        return WorkerOutcome(TaskState.OBSERVING, "observation_completed")


class UncertainHandler:
    async def handle(self, task):
        raise ExternalOutcomeUnknown("provider timed out after request submission")


def sample_task():
    return SimpleNamespace(
        task_id=uuid4(),
        version=4,
        lease_token=uuid4(),
        actor_id="trusted-actor",
        tenant_id="tenant-001",
        task_type="rag_observe",
    )


def registration():
    return WorkerRegistration(
        worker_id="local-worker-1",
        tier=WorkerTier.INLINE,
        tenant_id="tenant-001",
        task_types=("rag_observe",),
        lease_seconds=6,
        heartbeat_seconds=1,
    )


def test_worker_registration_rejects_duplicate_capabilities() -> None:
    config = WorkerRegistration(
        "worker-1", WorkerTier.DEDICATED, "tenant-001", ("render", "render"), 45, 10
    )
    with pytest.raises(ValueError, match="must_be_unique"):
        config.validate()


def test_worker_registration_requires_heartbeat_below_half_lease() -> None:
    config = WorkerRegistration(
        "worker-1", WorkerTier.INLINE, "tenant-001", ("rag_observe",), 10, 5
    )
    with pytest.raises(ValueError, match="less_than_half"):
        config.validate()


@pytest.mark.asyncio
async def test_worker_claims_and_transitions_task_with_fenced_lease() -> None:
    task = sample_task()
    store = FakeStore(task)
    worker = HybridWorker(
        store=store,
        registration=registration(),
        handlers={"rag_observe": GoodHandler()},
    )

    assert await worker.run_once() is True
    call = store.transition_calls[0]
    assert call["task_id"] == task.task_id
    assert call["expected_version"] == 4
    assert call["target"] is TaskState.OBSERVING
    assert call["lease"].worker_id == "local-worker-1"
    assert call["lease"].lease_token == task.lease_token


@pytest.mark.asyncio
async def test_unknown_external_outcome_is_blocked_not_retried() -> None:
    task = sample_task()
    store = FakeStore(task)
    worker = HybridWorker(
        store=store,
        registration=registration(),
        handlers={"rag_observe": UncertainHandler()},
    )

    await worker.run_once()
    call = store.transition_calls[0]
    assert call["target"] is TaskState.BLOCKED
    assert call["retryable"] is False
    assert call["error_code"] == "outcome_unknown"


@pytest.mark.asyncio
async def test_worker_returns_false_when_queue_is_empty() -> None:
    store = FakeStore(None)
    worker = HybridWorker(
        store=store,
        registration=registration(),
        handlers={"rag_observe": GoodHandler()},
    )
    assert await worker.run_once() is False
    assert store.transition_calls == []



class FakeRetrySchedulerStore:
    def __init__(self, tasks=None):
        self.tasks = list(tasks or [])
        self.calls = []

    async def requeue_due_retries(self, **kwargs):
        self.calls.append(kwargs)
        return self.tasks


def test_retry_scheduler_registration_bounds_batch_and_poll_interval() -> None:
    invalid = RetrySchedulerRegistration(
        scheduler_id="scheduler-1",
        tenant_id="tenant-001",
        batch_size=101,
    )
    with pytest.raises(ValueError, match="batch_size"):
        invalid.validate()


@pytest.mark.asyncio
async def test_retry_scheduler_runs_one_tenant_scoped_due_batch() -> None:
    store = FakeRetrySchedulerStore(tasks=[object(), object()])
    scheduler = RetryScheduler(
        store=store,
        registration=RetrySchedulerRegistration(
            scheduler_id="retry-scheduler-1",
            tenant_id="tenant-001",
            batch_size=10,
            poll_interval_seconds=1,
        ),
    )

    assert await scheduler.run_once() == 2
    assert store.calls == [
        {
            "tenant_id": "tenant-001",
            "scheduler_id": "retry-scheduler-1",
            "batch_size": 10,
        }
    ]


@pytest.mark.asyncio
async def test_retry_scheduler_stop_event_prevents_polling() -> None:
    store = FakeRetrySchedulerStore()
    scheduler = RetryScheduler(
        store=store,
        registration=RetrySchedulerRegistration(
            scheduler_id="retry-scheduler-1",
            tenant_id="tenant-001",
            poll_interval_seconds=1,
        ),
    )
    stop = asyncio.Event()
    stop.set()

    await scheduler.run(stop)
    assert store.calls == []


def test_worker_registration_rejects_boolean_lease_values() -> None:
    with pytest.raises(TypeError, match="lease_seconds_must_be_integer"):
        WorkerRegistration(
            "worker-1", WorkerTier.INLINE, "tenant-001", ("rag_observe",), True, 1
        ).validate()

    with pytest.raises(ValueError, match="heartbeat_interval_must_be_less_than_half"):
        WorkerRegistration(
            "worker-1", WorkerTier.INLINE, "tenant-001", ("rag_observe",), 10, True
        ).validate()


def test_worker_registration_rejects_non_enum_tier() -> None:
    config = WorkerRegistration(
        "worker-1", "inline", "tenant-001", ("rag_observe",), 10, 1
    )
    with pytest.raises(TypeError, match="worker_tier_invalid"):
        config.validate()


def test_worker_outcome_rejects_invalid_types() -> None:
    with pytest.raises(TypeError, match="worker_next_state_invalid"):
        WorkerOutcome("succeeded", "completed").validate()

    with pytest.raises(TypeError, match="worker_retryable_must_be_boolean"):
        WorkerOutcome(TaskState.FAILED, "retry_requested", retryable=1).validate()

    with pytest.raises(ValueError, match="worker_metadata_must_be_mapping"):
        WorkerOutcome(TaskState.SUCCEEDED, "completed", metadata=["unsafe"]).validate()


@pytest.mark.asyncio
async def test_worker_cancels_handler_on_unexpected_heartbeat_database_error() -> None:
    class DatabaseDriverError(Exception):
        pass

    class FailingHeartbeatStore(FakeStore):
        async def heartbeat(self, **kwargs):
            raise DatabaseDriverError("connection reset by database proxy")

    class BlockingHandler:
        def __init__(self):
            self.started = asyncio.Event()
            self.cancelled = asyncio.Event()

        async def handle(self, task):
            self.started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise

    task = sample_task()
    store = FailingHeartbeatStore(task)
    handler = BlockingHandler()
    worker = HybridWorker(
        store=store,
        registration=registration(),
        handlers={"rag_observe": handler},
    )

    with pytest.raises(LeaseLost, match="lost_lease"):
        await asyncio.wait_for(worker.run_once(), timeout=3)

    assert handler.started.is_set()
    assert handler.cancelled.is_set()
    assert store.transition_calls == []

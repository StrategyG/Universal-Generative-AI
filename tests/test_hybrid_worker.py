from types import SimpleNamespace
from uuid import uuid4

import pytest

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
    stop = __import__("asyncio").Event()
    stop.set()

    await scheduler.run(stop)
    assert store.calls == []

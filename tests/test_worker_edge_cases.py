from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ugai_workflow.state_machine import TaskState
from ugai_workflow.worker import (
    ExternalOutcomeUnknown,
    HybridWorker,
    LeaseLost,
    RetryableWorkerError,
    RetryScheduler,
    RetrySchedulerRegistration,
    WorkerOutcome,
    WorkerRegistration,
    WorkerTier,
)


def task(*, lease_token=None):
    return SimpleNamespace(
        task_id=uuid4(),
        version=1,
        lease_token=lease_token if lease_token is not None else uuid4(),
        actor_id="actor-a",
        tenant_id="tenant-a",
        task_type="summarize",
    )


def registration(**overrides):
    values = {
        "worker_id": "worker-a",
        "tier": WorkerTier.INLINE,
        "tenant_id": "tenant-a",
        "task_types": ("summarize",),
        "lease_seconds": 6,
        "heartbeat_seconds": 1,
    }
    values.update(overrides)
    return WorkerRegistration(**values)


class Store:
    def __init__(self, claimed=None, *, heartbeat_error=None):
        self.claimed = claimed
        self.heartbeat_error = heartbeat_error
        self.transitions = []
        self.heartbeats = []

    async def claim_next(self, **_kwargs):
        return self.claimed

    async def transition(self, **kwargs):
        self.transitions.append(kwargs)
        return self.claimed

    async def heartbeat(self, **kwargs):
        self.heartbeats.append(kwargs)
        if self.heartbeat_error:
            raise self.heartbeat_error
        return self.claimed


class ReturnOutcome:
    def __init__(self, outcome):
        self.outcome = outcome

    async def handle(self, _task):
        return self.outcome


class RaiseError:
    def __init__(self, error):
        self.error = error

    async def handle(self, _task):
        raise self.error


class WaitForever:
    async def handle(self, _task):
        await asyncio.Event().wait()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"worker_id": ""}, "worker_id_invalid"),
        ({"worker_id": "w" * 129}, "worker_id_invalid"),
        ({"tenant_id": " "}, "worker_tenant_id_invalid"),
        ({"tenant_id": "t" * 129}, "worker_tenant_id_invalid"),
        ({"tier": "inline"}, "worker_tier_invalid"),
        ({"task_types": ()}, "worker_task_types_required"),
        ({"task_types": (" ",)}, "worker_task_types_required"),
        ({"task_types": ("x" * 129,)}, "worker_task_types_required"),
        ({"lease_seconds": True}, "lease_seconds_out_of_bounds"),
        ({"lease_seconds": 4}, "lease_seconds_out_of_bounds"),
        ({"lease_seconds": 901}, "lease_seconds_out_of_bounds"),
        ({"heartbeat_seconds": True}, "heartbeat_interval_must_be_less_than_half"),
        ({"heartbeat_seconds": 3}, "heartbeat_interval_must_be_less_than_half"),
    ],
)
def test_worker_registration_rejects_invalid_boundaries(overrides, message):
    with pytest.raises(ValueError, match=message):
        registration(**overrides).validate()


@pytest.mark.parametrize(
    ("outcome", "message"),
    [
        (WorkerOutcome("succeeded", "done"), "worker_next_state_invalid"),
        (WorkerOutcome(TaskState.SUCCEEDED, "done", retryable=1), "worker_retryable_must_be_boolean"),
        (WorkerOutcome(TaskState.SUCCEEDED, "done", metadata=[]), "worker_metadata_must_be_mapping"),
        (WorkerOutcome(TaskState.SUCCEEDED, "Bad Code"), "worker_reason_code_invalid"),
        (WorkerOutcome(TaskState.SUCCEEDED, "done", error_code="Bad Code"), "worker_error_code_invalid"),
        (WorkerOutcome(TaskState.OBSERVING, "done", retryable=True), "only_failed_outcomes_may_be_retryable"),
        (WorkerOutcome(TaskState.AWAITING_APPROVAL, "done", approval_reference=" "), "worker_approval_reference_invalid"),
        (WorkerOutcome(TaskState.SUCCEEDED, "done", decision_digest="a" * 63), "worker_decision_digest_invalid"),
        (WorkerOutcome(TaskState.SUCCEEDED, "done", plan_digest="Z" * 64), "worker_plan_digest_invalid"),
    ],
)
def test_worker_outcome_rejects_invalid_contract_values(outcome, message):
    with pytest.raises(ValueError, match=message):
        outcome.validate()


def test_worker_outcome_accepts_valid_audit_metadata_and_digests():
    outcome = WorkerOutcome(
        next_state=TaskState.SUCCEEDED,
        reason_code="result_verified",
        metadata={"source_count": 2},
        approval_reference="approval-123",
        decision_digest="a" * 64,
        plan_digest="b" * 64,
    )
    outcome.validate()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"scheduler_id": ""}, "scheduler_id_invalid"),
        ({"tenant_id": ""}, "scheduler_tenant_id_invalid"),
        ({"batch_size": True}, "scheduler_batch_size_out_of_bounds"),
        ({"batch_size": 0}, "scheduler_batch_size_out_of_bounds"),
        ({"batch_size": 101}, "scheduler_batch_size_out_of_bounds"),
        ({"poll_interval_seconds": True}, "scheduler_poll_interval_out_of_bounds"),
        ({"poll_interval_seconds": 0.1}, "scheduler_poll_interval_out_of_bounds"),
        ({"poll_interval_seconds": 301}, "scheduler_poll_interval_out_of_bounds"),
    ],
)
def test_retry_scheduler_registration_rejects_invalid_boundaries(overrides, message):
    values = {"scheduler_id": "scheduler-a", "tenant_id": "tenant-a"}
    values.update(overrides)
    with pytest.raises(ValueError, match=message):
        RetrySchedulerRegistration(**values).validate()


def test_retry_scheduler_rejects_missing_store_and_invalid_stop_event():
    registration_value = RetrySchedulerRegistration("scheduler-a", "tenant-a")
    with pytest.raises(ValueError, match="workflow_store_required"):
        RetryScheduler(store=None, registration=registration_value)
    scheduler = RetryScheduler(store=Store(), registration=registration_value)
    with pytest.raises(TypeError, match="stop_event_must_be_asyncio_event"):
        asyncio.run(scheduler.run(None))


def test_retry_scheduler_repeats_after_poll_timeout_then_observes_shutdown(monkeypatch):
    store = Store()
    scheduler = RetryScheduler(
        store=store,
        registration=RetrySchedulerRegistration(
            "scheduler-a", "tenant-a", poll_interval_seconds=0.5
        ),
    )
    stop = asyncio.Event()
    calls = 0

    async def wait_for(_awaitable, *, timeout):
        nonlocal calls
        calls += 1
        assert timeout == 0.5
        if calls == 1:
            raise TimeoutError
        stop.set()
        return True

    monkeypatch.setattr("ugai_workflow.worker.asyncio.wait_for", wait_for)
    asyncio.run(scheduler.run(stop))
    assert len(store.transitions) == 0
    assert calls == 2


def test_worker_constructor_rejects_missing_store_and_non_mapping_handlers():
    with pytest.raises(ValueError, match="workflow_store_required"):
        HybridWorker(store=None, registration=registration(), handlers={})
    with pytest.raises(TypeError, match="handlers_must_be_mapping"):
        HybridWorker(store=Store(), registration=registration(), handlers=[])


def test_worker_blocks_task_when_handler_is_not_registered():
    claimed = task()
    store = Store(claimed)
    worker = HybridWorker(store=store, registration=registration(), handlers={})
    assert asyncio.run(worker.run_once()) is True
    assert store.transitions[0]["target"] is TaskState.BLOCKED
    assert store.transitions[0]["reason_code"] == "handler_not_registered"


def test_worker_rejects_claim_without_lease_token():
    claimed = task(lease_token=None)
    claimed.lease_token = None
    worker = HybridWorker(
        store=Store(claimed),
        registration=registration(),
        handlers={"summarize": ReturnOutcome(WorkerOutcome(TaskState.OBSERVING, "done"))},
    )
    with pytest.raises(LeaseLost, match="claimed_task_missing_lease_token"):
        asyncio.run(worker.run_once())


@pytest.mark.parametrize(
    ("error", "target", "retryable", "error_code"),
    [
        (RetryableWorkerError("temporary"), TaskState.FAILED, True, "retryable_worker_error"),
        (ExternalOutcomeUnknown("unknown"), TaskState.OUTCOME_UNKNOWN, False, "outcome_unknown"),
        (RuntimeError("internal"), TaskState.FAILED, False, "worker_unhandled_error"),
        (OSError("network"), TaskState.FAILED, False, "worker_unhandled_error"),
        (TimeoutError("timeout"), TaskState.FAILED, False, "worker_unhandled_error"),
        (ValueError("bad result"), TaskState.FAILED, False, "worker_unhandled_error"),
    ],
)
def test_worker_maps_handler_failures_to_explicit_safe_states(error, target, retryable, error_code):
    store = Store(task())
    worker = HybridWorker(
        store=store,
        registration=registration(),
        handlers={"summarize": RaiseError(error)},
    )
    assert asyncio.run(worker.run_once()) is True
    transition = store.transitions[0]
    assert transition["target"] is target
    assert transition["retryable"] is retryable
    assert transition["error_code"] == error_code


def test_worker_rejects_handler_returning_unvalidated_type_as_failure():
    store = Store(task())
    worker = HybridWorker(
        store=store,
        registration=registration(),
        handlers={"summarize": ReturnOutcome({"state": "succeeded"})},
    )
    assert asyncio.run(worker.run_once()) is True
    assert store.transitions[0]["target"] is TaskState.FAILED
    assert store.transitions[0]["error_code"] == "worker_unhandled_error"


def test_worker_propagates_cancellation_instead_of_marking_task_failed():
    store = Store(task())
    worker = HybridWorker(
        store=store,
        registration=registration(),
        handlers={"summarize": RaiseError(asyncio.CancelledError())},
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(worker.run_once())
    assert store.transitions == []


def test_worker_loses_lease_and_cancels_handler_when_heartbeat_fails():
    store = Store(task(), heartbeat_error=RuntimeError("heartbeat lost"))
    worker = HybridWorker(
        store=store,
        registration=registration(),
        handlers={"summarize": WaitForever()},
    )
    with pytest.raises(LeaseLost, match="worker_lost_lease_during_handler"):
        asyncio.run(worker.run_once())
    assert store.transitions == []
    assert len(store.heartbeats) == 1

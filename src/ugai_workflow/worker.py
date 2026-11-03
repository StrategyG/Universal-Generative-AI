"""Hybrid local/dedicated worker runner with lease heartbeats.

Handlers are application-owned code. A model response is not a handler and
cannot claim tasks, choose tools, or bypass workflow policy.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from .postgres_store import LeaseIdentity, LeaseLost, PostgresWorkflowStore, WorkflowTask
from .state_machine import TaskState

_CODE = re.compile(r"^[a-z][a-z0-9_:-]{0,79}$")


class WorkerTier(StrEnum):
    INLINE = "inline"
    DEDICATED = "dedicated"


@dataclass(frozen=True, slots=True)
class WorkerRegistration:
    worker_id: str
    tier: WorkerTier
    task_types: tuple[str, ...]
    lease_seconds: int = 45
    heartbeat_seconds: int = 12

    def validate(self) -> None:
        if not isinstance(self.worker_id, str) or not self.worker_id.strip() or len(self.worker_id) > 128:
            raise ValueError("worker_id_invalid")
        if not self.task_types or any(
            not isinstance(item, str) or not item.strip() or len(item) > 128
            for item in self.task_types
        ):
            raise ValueError("worker_task_types_required")
        if len(set(self.task_types)) != len(self.task_types):
            raise ValueError("worker_task_types_must_be_unique")
        if not 5 <= self.lease_seconds <= 900:
            raise ValueError("lease_seconds_out_of_bounds")
        if not 1 <= self.heartbeat_seconds < self.lease_seconds // 2:
            raise ValueError("heartbeat_interval_must_be_less_than_half_the_lease")


@dataclass(frozen=True, slots=True)
class WorkerOutcome:
    next_state: TaskState
    reason_code: str
    retryable: bool = False
    error_code: str | None = None
    metadata: Mapping[str, Any] | None = None

    def validate(self) -> None:
        if not _CODE.fullmatch(self.reason_code or ""):
            raise ValueError("worker_reason_code_invalid")
        if self.error_code is not None and not _CODE.fullmatch(self.error_code):
            raise ValueError("worker_error_code_invalid")
        if self.retryable and self.next_state is not TaskState.FAILED:
            raise ValueError("only_failed_outcomes_may_be_retryable")


class TaskHandler(Protocol):
    async def handle(self, task: WorkflowTask) -> WorkerOutcome:
        """Perform one bounded workflow stage using trusted application adapters."""


class RetryableWorkerError(RuntimeError):
    """A known-safe transient failure; no uncertain external write may remain."""


class ExternalOutcomeUnknown(RuntimeError):
    """External side effect may have completed; reconcile before any retry."""


class HybridWorker:
    """One worker process. Deploy inline and dedicated tiers as separate processes."""

    def __init__(
        self,
        *,
        store: PostgresWorkflowStore,
        registration: WorkerRegistration,
        handlers: Mapping[str, TaskHandler],
    ) -> None:
        registration.validate()
        if store is None:
            raise ValueError("workflow_store_required")
        if not isinstance(handlers, Mapping):
            raise ValueError("handlers_must_be_mapping")
        self.store = store
        self.registration = registration
        self.handlers = dict(handlers)

    async def run_once(self) -> bool:
        task = await self.store.claim_next(
            worker_id=self.registration.worker_id,
            supported_task_types=self.registration.task_types,
            lease_seconds=self.registration.lease_seconds,
        )
        if task is None:
            return False
        if task.lease_token is None:
            raise LeaseLost("claimed_task_missing_lease_token")

        lease = LeaseIdentity(self.registration.worker_id, task.lease_token)
        handler = self.handlers.get(task.task_type)
        if handler is None:
            outcome = WorkerOutcome(
                next_state=TaskState.BLOCKED,
                reason_code="handler_not_registered",
                error_code="handler_not_registered",
            )
        else:
            try:
                outcome = await self._handle_with_heartbeat(task, lease, handler)
            except LeaseLost:
                raise
            except RetryableWorkerError:
                outcome = WorkerOutcome(
                    next_state=TaskState.FAILED,
                    reason_code="retryable_worker_error",
                    retryable=True,
                    error_code="retryable_worker_error",
                )
            except ExternalOutcomeUnknown:
                outcome = WorkerOutcome(
                    next_state=TaskState.BLOCKED,
                    reason_code="external_outcome_unknown",
                    retryable=False,
                    error_code="outcome_unknown",
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                outcome = WorkerOutcome(
                    next_state=TaskState.FAILED,
                    reason_code="unhandled_worker_error",
                    retryable=False,
                    error_code="worker_unhandled_error",
                )

        outcome.validate()
        await self.store.transition(
            task_id=task.task_id,
            expected_version=task.version,
            target=outcome.next_state,
            actor_id=task.actor_id,
            reason_code=outcome.reason_code,
            lease=lease,
            retryable=outcome.retryable,
            error_code=outcome.error_code,
            metadata=outcome.metadata,
        )
        return True

    async def _handle_with_heartbeat(
        self,
        task: WorkflowTask,
        lease: LeaseIdentity,
        handler: TaskHandler,
    ) -> WorkerOutcome:
        lost_lease = asyncio.Event()

        async def heartbeat_loop() -> None:
            while True:
                await asyncio.sleep(self.registration.heartbeat_seconds)
                try:
                    await self.store.heartbeat(
                        task_id=task.task_id,
                        lease=lease,
                        lease_seconds=self.registration.lease_seconds,
                    )
                except Exception:
                    lost_lease.set()
                    return

        heartbeat_task = asyncio.create_task(heartbeat_loop())
        handler_task = asyncio.create_task(handler.handle(task))
        lost_task = asyncio.create_task(lost_lease.wait())
        try:
            done, _ = await asyncio.wait(
                {handler_task, lost_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if lost_task in done and lost_lease.is_set():
                handler_task.cancel()
                await asyncio.gather(handler_task, return_exceptions=True)
                raise LeaseLost("worker_lost_lease_during_handler")
            outcome = handler_task.result()
            if not isinstance(outcome, WorkerOutcome):
                raise TypeError("handler_must_return_WorkerOutcome")
            return outcome
        finally:
            for pending in (heartbeat_task, handler_task, lost_task):
                if not pending.done():
                    pending.cancel()
            await asyncio.gather(
                heartbeat_task, handler_task, lost_task, return_exceptions=True
            )

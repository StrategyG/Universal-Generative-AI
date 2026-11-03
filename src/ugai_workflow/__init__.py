"""Durable, fail-closed workflow runtime primitives for UGAI."""

from .postgres_store import (
    IdempotencyConflict,
    LeaseIdentity,
    LeaseLost,
    PostgresWorkflowStore,
    StaleWorkflowVersion,
    TaskNotFound,
    WorkflowTask,
)
from .state_machine import (
    CLAIMABLE_STATES,
    TERMINAL_STATES,
    TaskState,
    TransitionDenied,
    validate_transition,
)
from .worker import (
    ExternalOutcomeUnknown,
    HybridWorker,
    RetryableWorkerError,
    WorkerOutcome,
    WorkerRegistration,
    WorkerTier,
)

__all__ = [
    "CLAIMABLE_STATES",
    "ExternalOutcomeUnknown",
    "HybridWorker",
    "IdempotencyConflict",
    "LeaseIdentity",
    "LeaseLost",
    "PostgresWorkflowStore",
    "RetryableWorkerError",
    "StaleWorkflowVersion",
    "TERMINAL_STATES",
    "TaskNotFound",
    "TaskState",
    "TransitionDenied",
    "WorkflowTask",
    "WorkerOutcome",
    "WorkerRegistration",
    "WorkerTier",
    "validate_transition",
]

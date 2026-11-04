"""Deterministic task-state policy.

The model may propose an action, but only this application-owned policy and
the durable store may change persisted workflow state.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class TaskState(StrEnum):
    RECEIVED = "received"
    OBSERVING = "observing"
    PLANNING = "planning"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    AWAITING_APPROVAL = "awaiting_approval"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    BLOCKED = "blocked"
    FAILED = "failed"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"


TERMINAL_STATES: Final[frozenset[TaskState]] = frozenset(
    {TaskState.SUCCEEDED, TaskState.CANCELLED}
)

CLAIMABLE_STATES: Final[tuple[TaskState, ...]] = (
    TaskState.RECEIVED,
    TaskState.OBSERVING,
    TaskState.PLANNING,
    TaskState.EXECUTING,
    TaskState.VERIFYING,
)

_ALLOWED: Final[dict[TaskState, frozenset[TaskState]]] = {
    TaskState.RECEIVED: frozenset(
        {TaskState.OBSERVING, TaskState.BLOCKED, TaskState.FAILED, TaskState.CANCELLED}
    ),
    TaskState.OBSERVING: frozenset(
        {
            TaskState.PLANNING,
            TaskState.AWAITING_CLARIFICATION,
            TaskState.BLOCKED,
            TaskState.FAILED,
            TaskState.CANCELLED,
        }
    ),
    TaskState.PLANNING: frozenset(
        {
            TaskState.EXECUTING,
            TaskState.AWAITING_APPROVAL,
            TaskState.AWAITING_CLARIFICATION,
            TaskState.BLOCKED,
            TaskState.FAILED,
            TaskState.CANCELLED,
        }
    ),
    TaskState.EXECUTING: frozenset(
        {TaskState.VERIFYING, TaskState.AWAITING_APPROVAL, TaskState.BLOCKED, TaskState.FAILED}
    ),
    TaskState.VERIFYING: frozenset(
        {TaskState.SUCCEEDED, TaskState.FAILED, TaskState.BLOCKED}
    ),
    TaskState.AWAITING_APPROVAL: frozenset(
        {TaskState.EXECUTING, TaskState.FAILED, TaskState.CANCELLED}
    ),
    TaskState.AWAITING_CLARIFICATION: frozenset(
        {TaskState.OBSERVING, TaskState.CANCELLED}
    ),
    TaskState.BLOCKED: frozenset({TaskState.OBSERVING, TaskState.CANCELLED}),
    TaskState.FAILED: frozenset({TaskState.RECEIVED, TaskState.BLOCKED}),
    TaskState.SUCCEEDED: frozenset(),
    TaskState.CANCELLED: frozenset(),
}


class TransitionDenied(PermissionError):
    """A requested state transition violates workflow policy."""


def validate_transition(
    current: TaskState | str,
    target: TaskState | str,
    *,
    retry_count: int = 0,
    max_retries: int = 2,
    retryable: bool = False,
    approval_verified: bool = False,
    clarification_received: bool = False,
    operator_override: bool = False,
) -> tuple[TaskState, TaskState]:
    """Validate one transition without changing state or performing side effects."""
    try:
        source = TaskState(current)
        destination = TaskState(target)
    except (TypeError, ValueError) as exc:
        raise TransitionDenied("unknown_workflow_state") from exc

    if destination not in _ALLOWED[source]:
        raise TransitionDenied(f"transition_not_allowed:{source.value}->{destination.value}")

    if isinstance(retry_count, bool) or not isinstance(retry_count, int) or retry_count < 0:
        raise TransitionDenied("retry_count_invalid")
    if isinstance(max_retries, bool) or not isinstance(max_retries, int) or not 0 <= max_retries <= 2:
        raise TransitionDenied("max_retries_out_of_bounds")

    if (
        destination is TaskState.EXECUTING
        and source is TaskState.AWAITING_APPROVAL
        and not approval_verified
    ):
        raise TransitionDenied("verified_human_approval_required")

    if (
        source is TaskState.AWAITING_CLARIFICATION
        and destination is TaskState.OBSERVING
        and not clarification_received
    ):
        raise TransitionDenied("clarification_required")

    if source is TaskState.FAILED and destination is TaskState.RECEIVED:
        if not retryable:
            raise TransitionDenied("failure_not_marked_retryable")
        if retry_count >= max_retries:
            raise TransitionDenied("retry_limit_reached")

    if (
        source is TaskState.BLOCKED
        and destination is TaskState.OBSERVING
        and not operator_override
    ):
        raise TransitionDenied("operator_override_required")

    return source, destination

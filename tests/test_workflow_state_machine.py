import pytest

from ugai_workflow.state_machine import (
    CLAIMABLE_STATES,
    TaskState,
    TransitionDenied,
    validate_transition,
)


def test_happy_path_transitions_are_allowed() -> None:
    pairs = [
        (TaskState.RECEIVED, TaskState.OBSERVING),
        (TaskState.OBSERVING, TaskState.PLANNING),
        (TaskState.PLANNING, TaskState.EXECUTING),
        (TaskState.EXECUTING, TaskState.VERIFYING),
        (TaskState.VERIFYING, TaskState.SUCCEEDED),
    ]
    for source, target in pairs:
        assert validate_transition(source, target) == (source, target)


def test_awaiting_approval_requires_verified_receipt() -> None:
    with pytest.raises(TransitionDenied, match="verified_human_approval"):
        validate_transition(TaskState.AWAITING_APPROVAL, TaskState.EXECUTING)
    assert validate_transition(
        TaskState.AWAITING_APPROVAL, TaskState.EXECUTING, approval_verified=True
    )


def test_clarification_state_requires_user_input() -> None:
    with pytest.raises(TransitionDenied, match="clarification_required"):
        validate_transition(TaskState.AWAITING_CLARIFICATION, TaskState.OBSERVING)
    validate_transition(
        TaskState.AWAITING_CLARIFICATION, TaskState.OBSERVING, clarification_received=True
    )


def test_retry_requires_explicit_retryable_failure_and_remaining_budget() -> None:
    with pytest.raises(TransitionDenied, match="failure_not_marked_retryable"):
        validate_transition(TaskState.FAILED, TaskState.RECEIVED)
    with pytest.raises(TransitionDenied, match="retry_limit_reached"):
        validate_transition(
            TaskState.FAILED, TaskState.RECEIVED,
            retry_count=2, max_retries=2, retryable=True
        )
    validate_transition(
        TaskState.FAILED, TaskState.RECEIVED,
        retry_count=1, max_retries=2, retryable=True
    )


def test_blocked_recovery_requires_operator_override() -> None:
    with pytest.raises(TransitionDenied, match="operator_override"):
        validate_transition(TaskState.BLOCKED, TaskState.OBSERVING)
    validate_transition(
        TaskState.BLOCKED, TaskState.OBSERVING, operator_override=True
    )


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (TaskState.SUCCEEDED, TaskState.EXECUTING),
        (TaskState.CANCELLED, TaskState.RECEIVED),
        (TaskState.RECEIVED, TaskState.SUCCEEDED),
        (TaskState.OBSERVING, TaskState.EXECUTING),
        (TaskState.EXECUTING, TaskState.SUCCEEDED),
    ],
)
def test_invalid_transition_is_rejected(source: TaskState, target: TaskState) -> None:
    with pytest.raises(TransitionDenied):
        validate_transition(source, target)


def test_unknown_state_is_rejected() -> None:
    with pytest.raises(TransitionDenied, match="unknown_workflow_state"):
        validate_transition("completed", "succeeded")


def test_retry_budget_is_bounded() -> None:
    with pytest.raises(TransitionDenied, match="max_retries_out_of_bounds"):
        validate_transition(TaskState.FAILED, TaskState.RECEIVED, max_retries=3)



@pytest.mark.parametrize(
    ("retry_count", "max_retries", "error"),
    [
        (True, 2, "retry_count_invalid"),
        (0, True, "max_retries_out_of_bounds"),
    ],
)
def test_validate_transition_rejects_boolean_retry_counters(
    retry_count, max_retries, error
):
    with pytest.raises(TransitionDenied, match=error):
        validate_transition(
            TaskState.FAILED,
            TaskState.RECEIVED,
            retry_count=retry_count,
            max_retries=max_retries,
            retryable=True,
        )


def test_uncertain_outcome_requires_evidence_gated_reconciliation() -> None:
    assert validate_transition(TaskState.EXECUTING, TaskState.OUTCOME_UNKNOWN) == (
        TaskState.EXECUTING,
        TaskState.OUTCOME_UNKNOWN,
    )
    assert TaskState.OUTCOME_UNKNOWN not in CLAIMABLE_STATES
    with pytest.raises(TransitionDenied, match="reconciliation_evidence_required"):
        validate_transition(TaskState.OUTCOME_UNKNOWN, TaskState.VERIFYING)
    assert validate_transition(
        TaskState.OUTCOME_UNKNOWN,
        TaskState.VERIFYING,
        reconciliation_verified=True,
    ) == (TaskState.OUTCOME_UNKNOWN, TaskState.VERIFYING)


def test_uncertain_outcome_cannot_be_retried_or_reconciled_without_evidence() -> None:
    for target in (TaskState.EXECUTING, TaskState.RECEIVED, TaskState.SUCCEEDED):
        with pytest.raises(TransitionDenied):
            validate_transition(TaskState.OUTCOME_UNKNOWN, target)
    with pytest.raises(TransitionDenied, match="reconciliation_flag_not_applicable"):
        validate_transition(
            TaskState.EXECUTING,
            TaskState.VERIFYING,
            reconciliation_verified=True,
        )

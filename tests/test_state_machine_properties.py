from __future__ import annotations

import pytest
from hypothesis import given, strategies as st

from app.auth import _string_set
from ugai_workflow.state_machine import TaskState, TransitionDenied, validate_transition


ALLOWED_TRANSITIONS = {
    TaskState.RECEIVED: {
        TaskState.OBSERVING, TaskState.BLOCKED, TaskState.FAILED, TaskState.CANCELLED
    },
    TaskState.OBSERVING: {
        TaskState.PLANNING, TaskState.AWAITING_CLARIFICATION,
        TaskState.BLOCKED, TaskState.FAILED, TaskState.CANCELLED
    },
    TaskState.PLANNING: {
        TaskState.EXECUTING, TaskState.AWAITING_APPROVAL,
        TaskState.AWAITING_CLARIFICATION, TaskState.BLOCKED,
        TaskState.FAILED, TaskState.CANCELLED
    },
    TaskState.EXECUTING: {
        TaskState.VERIFYING, TaskState.OUTCOME_UNKNOWN,
        TaskState.AWAITING_APPROVAL, TaskState.BLOCKED, TaskState.FAILED
    },
    TaskState.OUTCOME_UNKNOWN: {TaskState.VERIFYING},
    TaskState.VERIFYING: {TaskState.SUCCEEDED, TaskState.FAILED, TaskState.BLOCKED},
    TaskState.AWAITING_APPROVAL: {
        TaskState.EXECUTING, TaskState.FAILED, TaskState.CANCELLED
    },
    TaskState.AWAITING_CLARIFICATION: {
        TaskState.OBSERVING, TaskState.CANCELLED
    },
    TaskState.BLOCKED: {TaskState.OBSERVING, TaskState.CANCELLED},
    TaskState.FAILED: {
        TaskState.RECEIVED, TaskState.BLOCKED, TaskState.CANCELLED
    },
    TaskState.SUCCEEDED: set(),
    TaskState.CANCELLED: set(),
}


def _valid_gate_arguments(source: TaskState, target: TaskState) -> dict:
    arguments = {}
    if source is TaskState.OUTCOME_UNKNOWN and target is TaskState.VERIFYING:
        arguments["reconciliation_verified"] = True
    if source is TaskState.AWAITING_APPROVAL and target is TaskState.EXECUTING:
        arguments["approval_verified"] = True
    if source is TaskState.AWAITING_CLARIFICATION and target is TaskState.OBSERVING:
        arguments["clarification_received"] = True
    if source is TaskState.BLOCKED and target is TaskState.OBSERVING:
        arguments["operator_override"] = True
    if source is TaskState.FAILED and target is TaskState.RECEIVED:
        arguments.update(retryable=True, retry_count=0, max_retries=2)
    return arguments


@pytest.mark.parametrize("source", list(TaskState))
@pytest.mark.parametrize("target", list(TaskState))
def test_every_workflow_state_pair_obeys_the_transition_matrix(source, target):
    allowed = target in ALLOWED_TRANSITIONS[source]
    if not allowed:
        with pytest.raises(TransitionDenied):
            validate_transition(source, target)
        return

    result = validate_transition(source, target, **_valid_gate_arguments(source, target))
    assert result == (source, target)


@pytest.mark.parametrize("terminal", [TaskState.SUCCEEDED, TaskState.CANCELLED])
def test_terminal_states_cannot_transition(terminal):
    for target in TaskState:
        with pytest.raises(TransitionDenied):
            validate_transition(terminal, target)


def test_uncertain_external_outcome_requires_explicit_reconciliation_evidence():
    with pytest.raises(TransitionDenied, match="reconciliation_evidence_required"):
        validate_transition(TaskState.OUTCOME_UNKNOWN, TaskState.VERIFYING)
    with pytest.raises(TransitionDenied, match="reconciliation_flag_not_applicable"):
        validate_transition(
            TaskState.RECEIVED,
            TaskState.OBSERVING,
            reconciliation_verified=True,
        )


def test_retry_limits_and_operator_approval_are_fail_closed():
    with pytest.raises(TransitionDenied, match="retry_limit_reached"):
        validate_transition(
            TaskState.FAILED,
            TaskState.RECEIVED,
            retryable=True,
            retry_count=2,
            max_retries=2,
        )
    with pytest.raises(TransitionDenied, match="verified_human_approval_required"):
        validate_transition(TaskState.AWAITING_APPROVAL, TaskState.EXECUTING)
    with pytest.raises(TransitionDenied, match="operator_override_required"):
        validate_transition(TaskState.BLOCKED, TaskState.OBSERVING)


@given(st.lists(st.text(), max_size=40))
def test_string_claim_normalization_is_deterministic_and_deduplicated(values):
    expected = frozenset(value.strip() for value in values if value.strip())
    assert _string_set(values, "roles") == expected


@given(st.text())
def test_scalar_string_claim_is_normalized_without_inventing_values(value):
    expected = frozenset({value.strip()}) if value.strip() else frozenset()
    assert _string_set(value, "roles") == expected


@given(st.one_of(st.integers(), st.floats(allow_nan=False), st.dictionaries(st.text(), st.text())))
def test_non_string_claim_shapes_are_rejected(value):
    with pytest.raises(ValueError, match="must be a string or array of strings"):
        _string_set(value, "roles")

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from ugai_workflow.postgres_store import (
    LeaseIdentity,
    PostgresWorkflowStore,
    WorkflowTask,
    _safe_event_details,
    _safe_metadata,
    canonical_json_digest,
    retry_backoff_seconds,
)
from ugai_workflow.state_machine import TaskState


class PoolPlaceholder:
    def acquire(self):
        raise AssertionError("validation must fail before database acquisition")


def store():
    return PostgresWorkflowStore(PoolPlaceholder())


def create_args(**overrides):
    values = {
        "tenant_id": "tenant-a",
        "actor_id": "actor-a",
        "task_type": "notebook_task",
        "idempotency_key": "idempotency-001",
        "input_digest": "a" * 64,
        "encrypted_payload": b"encrypted",
        "payload_key_id": "key-v1",
        "payload_sha256": "a" * 64,
    }
    values.update(overrides)
    return values


def result_args(**overrides):
    values = {
        "tenant_id": "tenant-a",
        "actor_id": "actor-a",
        "project_id": "project-a",
        "task_id": uuid4(),
        "key_id": "key-v1",
        "ciphertext": b"encrypted-result",
        "payload_sha256": "b" * 64,
    }
    values.update(overrides)
    return values


def transition_args(**overrides):
    values = {
        "task_id": uuid4(),
        "tenant_id": "tenant-a",
        "expected_version": 0,
        "target": TaskState.CANCELLED,
        "actor_id": "actor-a",
        "reason_code": "user_cancelled",
        "require_lease": False,
    }
    values.update(overrides)
    return values


def test_workflow_task_record_decodes_string_and_empty_metadata():
    row = {
        "task_id": uuid4(),
        "tenant_id": "tenant-a",
        "actor_id": "actor-a",
        "task_type": "notebook_task",
        "state": "received",
        "version": 0,
        "retry_count": 0,
        "max_retries": 2,
        "retryable": False,
        "idempotency_key": "idempotency-001",
        "input_digest": "a" * 64,
        "priority": 0,
        "available_at": datetime.now(UTC),
        "lease_owner": None,
        "lease_token": None,
        "lease_expires_at": None,
        "approval_reference": None,
        "decision_digest": None,
        "plan_digest": None,
        "error_code": None,
        "metadata": json.dumps({"context_ref": "safe-ref"}),
    }
    decoded = WorkflowTask.from_record(row)
    assert decoded.metadata == {"context_ref": "safe-ref"}
    row["metadata"] = None
    assert WorkflowTask.from_record(row).metadata == {}


def test_canonical_json_digest_rejects_non_objects_non_finite_and_oversized_values():
    with pytest.raises(TypeError, match="json_value_must_be_object"):
        canonical_json_digest(["not", "an", "object"])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="value_must_be_finite_json"):
        canonical_json_digest({"value": float("nan")})
    with pytest.raises(ValueError, match="json_value_too_large"):
        canonical_json_digest({"value": "x" * (64 * 1024)})


def test_safe_metadata_and_event_details_enforce_allowlists_and_scalar_types():
    assert _safe_metadata(None) == {}
    assert _safe_metadata({"context_ref": "ref-1", "schema_version": "1.0"}) == {
        "context_ref": "ref-1",
        "schema_version": "1.0",
    }
    with pytest.raises(TypeError, match="metadata_must_be_object"):
        _safe_metadata([])
    with pytest.raises(ValueError, match="metadata_key_not_allowlisted"):
        _safe_metadata({"prompt": "must-not-be-stored"})
    with pytest.raises(ValueError, match="metadata_value_invalid"):
        _safe_metadata({"context_ref": " "})

    assert _safe_event_details(None) == {}
    assert _safe_event_details({"attempt": 2, "error_code": "retryable_error"}) == {
        "attempt": 2,
        "error_code": "retryable_error",
    }
    with pytest.raises(TypeError, match="event_metadata_must_be_object"):
        _safe_event_details([])
    with pytest.raises(ValueError, match="event_metadata_key_not_allowlisted"):
        _safe_event_details({"secret": "value"})
    assert _safe_event_details({"attempt": True}) == {"attempt": True}
    with pytest.raises(ValueError, match="event_metadata_value_invalid"):
        _safe_event_details({"attempt": -1})


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"tenant_id": ""}, "tenant_id_invalid"),
        ({"actor_id": ""}, "actor_id_invalid"),
        ({"task_type": ""}, "task_type_invalid"),
        ({"project_id": ""}, "project_id_invalid"),
        ({"idempotency_key": "short"}, "idempotency_key_invalid"),
        ({"input_digest": "not-a-digest"}, "input_digest_must_be_sha256"),
        ({"priority": True}, "priority_out_of_bounds"),
        ({"priority": 101}, "priority_out_of_bounds"),
        ({"max_retries": True}, "max_retries_must_be_between_0_and_2"),
        ({"max_retries": 3}, "max_retries_must_be_between_0_and_2"),
        ({"encrypted_payload": b""}, "encrypted_payload_size_invalid"),
        ({"encrypted_payload": "not-bytes"}, "encrypted_payload_size_invalid"),
        ({"payload_key_id": ""}, "payload_key_id_invalid"),
        ({"payload_sha256": "bad"}, "payload_sha256_must_be_sha256"),
        ({"payload_sha256": "b" * 64}, "payload_digest_must_match_task_input_digest"),
        ({"encrypted_payload": None, "payload_key_id": "key-v1"}, "payload_metadata_requires_encrypted_payload"),
        ({"metadata": {"prompt": "not allowlisted"}}, "metadata_key_not_allowlisted"),
    ],
)
def test_create_task_rejects_invalid_input_before_database_access(overrides, message):
    with pytest.raises((TypeError, ValueError), match=message):
        asyncio.run(store().create_task(**create_args(**overrides)))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"tenant_id": ""}, "tenant_id_invalid"),
        ({"actor_id": ""}, "actor_id_invalid"),
        ({"project_id": ""}, "project_id_invalid"),
        ({"key_id": ""}, "result_key_id_invalid"),
        ({"task_id": "not-a-uuid"}, "task_id_invalid"),
        ({"ciphertext": b""}, "result_ciphertext_size_invalid"),
        ({"ciphertext": "not-bytes"}, "result_ciphertext_size_invalid"),
        ({"payload_sha256": "invalid"}, "result_payload_sha256_invalid"),
    ],
)
def test_put_encrypted_result_rejects_invalid_values_before_database_access(overrides, message):
    with pytest.raises(ValueError, match=message):
        asyncio.run(store().put_encrypted_result(**result_args(**overrides)))


def test_get_encrypted_result_and_payload_validate_tenant_and_uuid():
    with pytest.raises(ValueError, match="tenant_id_invalid"):
        asyncio.run(store().get_encrypted_result(tenant_id="", task_id=uuid4()))
    with pytest.raises(ValueError, match="task_id_invalid"):
        asyncio.run(store().get_encrypted_result(tenant_id="tenant-a", task_id="bad"))
    with pytest.raises(ValueError, match="tenant_id_invalid"):
        asyncio.run(store().get_encrypted_payload(task_id=uuid4(), tenant_id=""))


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"tenant_id": "", "worker_id": "worker-a", "task_types": ("task-a",)}, "tenant_id_invalid"),
        ({"tenant_id": "tenant-a", "worker_id": "", "task_types": ("task-a",)}, "worker_id_invalid"),
        ({"tenant_id": "tenant-a", "worker_id": "worker-a", "task_types": ()}, "worker_task_types_required"),
        ({"tenant_id": "tenant-a", "worker_id": "worker-a", "task_types": (" ",)}, "worker_task_types_required"),
        ({"tenant_id": "tenant-a", "worker_id": "worker-a", "task_types": ("task-a", "task-a")}, "worker_task_types_must_be_unique"),
    ],
)
def test_worker_registration_validation_rejects_invalid_scope_and_capabilities(kwargs, message):
    with pytest.raises(ValueError, match=message):
        asyncio.run(store().heartbeat_worker(**kwargs))


def test_worker_health_and_outcome_unknown_list_validate_bounds():
    with pytest.raises(ValueError, match="worker_health_window_out_of_bounds"):
        asyncio.run(store().has_healthy_worker(
            tenant_id="tenant-a", task_type="notebook_task", max_age_seconds=True
        ))
    with pytest.raises(ValueError, match="outcome_unknown_limit_out_of_bounds"):
        asyncio.run(store().list_outcome_unknown(tenant_id="tenant-a", limit=0))
    with pytest.raises(ValueError, match="outcome_unknown_limit_out_of_bounds"):
        asyncio.run(store().list_outcome_unknown(tenant_id="tenant-a", limit=True))


def test_claim_and_heartbeat_validate_worker_lease_inputs():
    with pytest.raises(ValueError, match="supported_task_types_required"):
        asyncio.run(store().claim_next(
            tenant_id="tenant-a", worker_id="worker-a", supported_task_types=()
        ))
    with pytest.raises(ValueError, match="lease_seconds_out_of_bounds"):
        asyncio.run(store().claim_next(
            tenant_id="tenant-a", worker_id="worker-a",
            supported_task_types=("notebook_task",), lease_seconds=True
        ))
    with pytest.raises(ValueError, match="lease_seconds_out_of_bounds"):
        asyncio.run(store().heartbeat(
            task_id=uuid4(), tenant_id="tenant-a",
            lease=LeaseIdentity("worker-a", uuid4()), lease_seconds=0
        ))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"reason_code": "Bad Code"}, "reason_code_invalid"),
        ({"error_code": "Bad Code"}, "error_code_invalid"),
        ({"expected_version": -1}, "expected_version_invalid"),
        ({"retry_delay_seconds": True}, "retry_delay_seconds_out_of_bounds"),
        ({"retry_delay_seconds": 86_401}, "retry_delay_seconds_out_of_bounds"),
        ({"approval_reference": " "}, "approval_reference_invalid"),
        ({"decision_digest": "bad"}, "decision_digest_must_be_sha256"),
        ({"plan_digest": "bad"}, "plan_digest_must_be_sha256"),
        ({"reconciliation_verified": "yes"}, "reconciliation_verified_must_be_boolean"),
        ({"metadata": {"private_prompt": "secret"}}, "event_metadata_key_not_allowlisted"),
        ({"metadata": {"attempt": -1}}, "event_metadata_value_invalid"),
    ],
)
def test_transition_rejects_invalid_audit_and_fencing_arguments(overrides, message):
    with pytest.raises((TypeError, ValueError), match=message):
        asyncio.run(store().transition(**transition_args(**overrides)))


def test_retry_requeue_rejects_invalid_batch_size_and_backoff_inputs():
    with pytest.raises(ValueError, match="retry_batch_size_out_of_bounds"):
        asyncio.run(store().requeue_due_retries(
            tenant_id="tenant-a", scheduler_id="scheduler-a", batch_size=True
        ))
    with pytest.raises(ValueError, match="retry_attempt_invalid"):
        retry_backoff_seconds(-1)
    with pytest.raises(ValueError, match="retry_attempt_invalid"):
        retry_backoff_seconds(True)
    with pytest.raises(ValueError, match="retry_base_delay_out_of_bounds"):
        retry_backoff_seconds(0, base_delay_seconds=0)
    with pytest.raises(ValueError, match="retry_max_delay_out_of_bounds"):
        retry_backoff_seconds(0, base_delay_seconds=10, max_delay_seconds=5)
    assert retry_backoff_seconds(20, base_delay_seconds=30, max_delay_seconds=300) == 300

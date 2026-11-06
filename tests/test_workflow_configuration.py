from __future__ import annotations

import pytest

from app.config import (
    Settings,
    validate_workflow_task_configuration,
    validate_workflow_worker_configuration,
)


def task_settings(**overrides) -> Settings:
    values = {
        "environment": "development",
        "workflow_task_api_enabled": True,
        "workflow_database_url": "postgresql://api:api-secret@db.example.test:5432/ugai",
        "workflow_payload_encryption_key": "test-encryption-key",
        "workflow_payload_key_id": "active-v2",
        "workflow_payload_previous_keys_json": '{"active-v1":"old-encryption-key"}',
    }
    values.update(overrides)
    return Settings(**values)


def worker_settings(**overrides) -> Settings:
    values = {
        "environment": "development",
        "workflow_task_api_enabled": True,
        "workflow_database_url": "postgresql://api:api-secret@db.example.test:5432/ugai",
        "workflow_payload_encryption_key": "test-encryption-key",
        "workflow_worker_enabled": True,
        "workflow_worker_database_url": "postgresql://worker:worker-secret@db.example.test:5432/ugai",
        "workflow_worker_tenant_id": "tenant-test",
        "workflow_worker_id": "worker-test",
        "workflow_worker_lease_seconds": 60,
        "workflow_worker_heartbeat_seconds": 10,
    }
    values.update(overrides)
    return Settings(**values)


def test_workflow_task_api_is_optional_outside_production():
    validate_workflow_task_configuration(
        Settings(environment="development", workflow_task_api_enabled=False)
    )


def test_production_requires_task_api_to_be_explicitly_enabled():
    with pytest.raises(RuntimeError, match="WORKFLOW_TASK_API_ENABLED"):
        validate_workflow_task_configuration(
            Settings(environment="production", workflow_task_api_enabled=False)
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"workflow_database_url": ""}, "WORKFLOW_DATABASE_URL is required"),
        ({"workflow_payload_encryption_key": " "}, "WORKFLOW_PAYLOAD_ENCRYPTION_KEY"),
        ({"workflow_payload_key_id": ""}, "WORKFLOW_PAYLOAD_KEY_ID"),
        ({"workflow_payload_key_id": "k" * 65}, "WORKFLOW_PAYLOAD_KEY_ID"),
        ({"workflow_payload_previous_keys_json": "{"}, "must be valid JSON"),
        ({"workflow_payload_previous_keys_json": "[]"}, "must be an object"),
        ({"workflow_payload_previous_keys_json": '{"active-v2":"duplicate"}'}, "invalid key entry"),
        ({"workflow_payload_previous_keys_json": '{" ":"old"}'}, "invalid key entry"),
        ({"workflow_payload_previous_keys_json": '{"old":""}'}, "invalid key entry"),
        ({"workflow_database_url": "mysql://api:secret@db.example.test/ugai"}, "PostgreSQL URL"),
        ({"workflow_database_url": "postgresql://[invalid"}, "WORKFLOW_DATABASE_URL is invalid"),
    ],
)
def test_workflow_task_configuration_rejects_invalid_values(overrides, message):
    with pytest.raises(RuntimeError, match=message):
        validate_workflow_task_configuration(task_settings(**overrides))


def test_production_workflow_database_requires_exact_verify_full_sslmode():
    for dsn in (
        "postgresql://api:secret@db.example.test:5432/ugai",
        "postgresql://api:secret@db.example.test:5432/ugai?sslmode=require",
        "postgresql://api:secret@db.example.test:5432/ugai?sslmode=verify-full&sslmode=require",
    ):
        with pytest.raises(RuntimeError, match="sslmode=verify-full"):
            validate_workflow_task_configuration(
                task_settings(environment="production", workflow_database_url=dsn)
            )

    validate_workflow_task_configuration(
        task_settings(
            environment="production",
            workflow_database_url=(
                "postgresql://api:secret@db.example.test:5432/ugai?sslmode=verify-full"
            ),
        )
    )


def test_workflow_worker_disabled_is_a_noop():
    validate_workflow_worker_configuration(Settings(workflow_worker_enabled=False))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"workflow_task_api_enabled": False}, "WORKFLOW_TASK_API_ENABLED"),
        ({"workflow_worker_tenant_id": ""}, "WORKFLOW_WORKER_TENANT_ID"),
        ({"workflow_worker_tenant_id": "t" * 129}, "WORKFLOW_WORKER_TENANT_ID"),
        ({"workflow_worker_id": ""}, "WORKFLOW_WORKER_ID"),
        ({"workflow_worker_id": "w" * 129}, "WORKFLOW_WORKER_ID"),
        ({"workflow_worker_heartbeat_seconds": 30}, "less than half the lease"),
        ({"workflow_worker_database_url": ""}, "WORKFLOW_WORKER_DATABASE_URL is required"),
        ({"workflow_worker_database_url": "mysql://worker:secret@db.example.test/ugai"}, "PostgreSQL URL"),
        ({"workflow_worker_database_url": "postgresql://[invalid"}, "WORKFLOW_WORKER_DATABASE_URL is invalid"),
        (
            {"workflow_worker_database_url": "postgresql://api:other@db.example.test:5432/ugai"},
            "logins must be distinct",
        ),
    ],
)
def test_workflow_worker_configuration_rejects_invalid_values(overrides, message):
    with pytest.raises(RuntimeError, match=message):
        validate_workflow_worker_configuration(worker_settings(**overrides))


def test_production_worker_database_requires_verify_full_and_distinct_login():
    with pytest.raises(RuntimeError, match="sslmode=verify-full"):
        validate_workflow_worker_configuration(
            worker_settings(
                environment="production",
                workflow_database_url="postgresql://api:secret@db.example.test/ugai?sslmode=verify-full",
                workflow_worker_database_url="postgresql://worker:secret@db.example.test/ugai",
            )
        )

    validate_workflow_worker_configuration(
        worker_settings(
            environment="production",
            workflow_database_url="postgresql://api:secret@db.example.test/ugai?sslmode=verify-full",
            workflow_worker_database_url="postgresql://worker:secret@db.example.test/ugai?sslmode=verify-full",
        )
    )

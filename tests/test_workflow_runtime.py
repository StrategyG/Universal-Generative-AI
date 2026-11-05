from __future__ import annotations

import base64
import json
from contextlib import asynccontextmanager

import pytest

from app.config import Settings
from app.workflow_runtime import (
    _assert_restricted_runtime_role,
    _decode_keyring,
    _enabled_task_types,
    _validate_workflow_database_url,
)


def _settings(**overrides) -> Settings:
    return Settings(**overrides)


def test_keyring_accepts_only_32_byte_base64_keys() -> None:
    key = bytes(range(32))
    config = _settings(
        workflow_input_keyring_json=json.dumps(
            {"primary-v1": base64.b64encode(key).decode("ascii")}
        ),
        workflow_input_active_key_id="primary-v1",
    )
    assert _decode_keyring(config) == {"primary-v1": key}


@pytest.mark.parametrize(
    "keyring,active_key_id",
    [
        ("{}", "missing"),
        ('{"primary-v1":"not-base64!"}', "primary-v1"),
        (
            json.dumps({"primary-v1": base64.b64encode(b"short").decode("ascii")}),
            "primary-v1",
        ),
    ],
)
def test_keyring_rejects_invalid_or_missing_keys(keyring: str, active_key_id: str) -> None:
    config = _settings(
        workflow_input_keyring_json=keyring,
        workflow_input_active_key_id=active_key_id,
    )
    with pytest.raises(RuntimeError):
        _decode_keyring(config)


def test_production_database_url_requires_full_tls_verification() -> None:
    config = _settings(
        environment="production",
        workflow_database_url=(
            "postgresql://ugai_runtime:secret@db.example.test:5432/ugai"
            "?sslmode=verify-full"
        ),
    )
    _validate_workflow_database_url(config)


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://ugai_runtime:secret@db.example.test:5432/ugai",
        "postgresql://ugai_runtime:secret@db.example.test:5432/ugai?sslmode=require",
        "https://db.example.test",
    ],
)
def test_production_database_url_rejects_weak_or_invalid_dsn(dsn: str) -> None:
    config = _settings(environment="production", workflow_database_url=dsn)
    with pytest.raises(RuntimeError):
        _validate_workflow_database_url(config)


def test_enabled_task_types_are_unique_and_bounded() -> None:
    config = _settings(workflow_enabled_task_types="decision_evaluation,notebook_request")
    assert _enabled_task_types(config) == frozenset(
        {"decision_evaluation", "notebook_request"}
    )
    with pytest.raises(RuntimeError):
        _enabled_task_types(
            _settings(workflow_enabled_task_types="notebook_request,notebook_request")
        )


class _FakeConnection:
    def __init__(self, row):
        self.row = row

    async def fetchrow(self, _query: str):
        return self.row


class _FakePool:
    def __init__(self, row):
        self.connection = _FakeConnection(row)

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


def _restricted_role_row(**overrides):
    row = {
        "role_name": "ugai_runtime_login",
        "is_superuser": False,
        "bypasses_rls": False,
        "runtime_role_member": True,
        "not_schema_owner": True,
        "not_table_owner": True,
        "schema_usage": True,
        "task_select": True,
        "task_insert": True,
        "event_insert": True,
        "input_select": True,
        "input_insert": True,
        "result_select": True,
        "result_insert": True,
        "worker_select": True,
        "worker_insert": True,
        "worker_update": True,
        "workspace_binding_select": True,
    }
    row.update(overrides)
    return row


@pytest.mark.asyncio
async def test_runtime_database_role_requires_non_owner_runtime_membership() -> None:
    await _assert_restricted_runtime_role(_FakePool(_restricted_role_row()))


@pytest.mark.parametrize(
    "override",
    [
        {"is_superuser": True},
        {"bypasses_rls": True},
        {"runtime_role_member": False},
        {"not_schema_owner": False},
        {"not_table_owner": False},
        {"input_select": False},
        {"result_select": False},
        {"result_insert": False},
        {"worker_select": False},
        {"worker_insert": False},
        {"worker_update": False},
        {"workspace_binding_select": False},
    ],
)
@pytest.mark.asyncio
async def test_runtime_database_role_rejects_privileged_or_incomplete_role(override) -> None:
    with pytest.raises(RuntimeError, match="restricted non-owner"):
        await _assert_restricted_runtime_role(
            _FakePool(_restricted_role_row(**override))
        )

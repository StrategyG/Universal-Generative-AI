from __future__ import annotations

import asyncio
import sys
from types import ModuleType, SimpleNamespace

import pytest

from app import notebook_worker as module


class Acquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *_args):
        return None


class Connection:
    def __init__(self, row):
        self.row = row

    async def fetchrow(self, _query):
        return self.row


class Pool:
    def __init__(self, row):
        self.connection = Connection(row)
        self.closed = False

    def acquire(self):
        return Acquire(self.connection)

    async def close(self):
        self.closed = True


def role_row(**overrides):
    row = {
        "is_superuser": False,
        "bypasses_rls": False,
        "worker_role_member": True,
        "api_runtime_role_member": False,
        "not_schema_owner": True,
        "not_table_owner": True,
        "tasks_select": True,
        "tasks_update": True,
        "events_insert": True,
        "payloads_select": True,
        "results_insert": True,
        "workers_update": True,
    }
    row.update(overrides)
    return row


@pytest.mark.asyncio
async def test_worker_database_role_accepts_only_distinct_least_privilege_login():
    await module._assert_worker_database_role(Pool(role_row()))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "row",
    [
        None,
        role_row(is_superuser=True),
        role_row(bypasses_rls=True),
        role_row(worker_role_member=False),
        role_row(api_runtime_role_member=True),
        role_row(not_schema_owner=False),
        role_row(not_table_owner=False),
        role_row(results_insert=False),
    ],
)
async def test_worker_database_role_rejects_privileged_or_incomplete_login(row):
    with pytest.raises(RuntimeError, match="distinct, non-owner, NOBYPASSRLS"):
        await module._assert_worker_database_role(Pool(row))


def worker_settings(monkeypatch, **overrides):
    values = {
        "workflow_worker_enabled": True,
        "workflow_worker_database_url": "postgresql://worker:secret@db.test/ugai",
        "workflow_payload_previous_keys_json": "{}",
        "workflow_payload_encryption_key": "test-encryption-key",
        "workflow_payload_key_id": "test-v1",
        "workflow_worker_id": "notebook-worker-test",
        "workflow_worker_tenant_id": "tenant-test",
        "workflow_worker_lease_seconds": 60,
        "workflow_worker_heartbeat_seconds": 10,
        "workflow_worker_poll_seconds": 0.01,
    }
    values.update(overrides)
    for key, value in values.items():
        monkeypatch.setattr(module.settings, key, value)


def install_worker_fakes(monkeypatch, *, mode="success", role=None):
    pool = Pool(role if role is not None else role_row())
    store = SimpleNamespace(
        heartbeat_calls=0,
        deregister_calls=[],
        async_heartbeat_error=False,
    )

    async def create_pool(**_kwargs):
        return pool

    async def heartbeat_worker(**kwargs):
        store.heartbeat_calls += 1
        if mode == "initial_heartbeat_failure" and store.heartbeat_calls == 1:
            raise RuntimeError("registry unavailable")
        if mode == "heartbeat_failure" and store.heartbeat_calls == 2:
            raise RuntimeError("heartbeat lost")
        if mode == "heartbeat_stop" and store.heartbeat_calls == 2:
            event_holder["event"].set()

    async def deregister_worker(**kwargs):
        store.deregister_calls.append(kwargs)

    store.heartbeat_worker = heartbeat_worker
    store.deregister_worker = deregister_worker

    asyncpg = ModuleType("asyncpg")
    asyncpg.create_pool = create_pool
    monkeypatch.setitem(sys.modules, "asyncpg", asyncpg)

    monkeypatch.setattr(module, "validate_database_configuration", lambda: None)
    monkeypatch.setattr(module, "validate_workflow_task_configuration", lambda: None)
    monkeypatch.setattr(module, "validate_workflow_worker_configuration", lambda: None)
    monkeypatch.setattr(module, "TaskPayloadCipher", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(module, "PostgresWorkflowStore", lambda _pool: store)

    calls = {"initialize": 0, "close": 0, "reconcile": 0}

    async def initialize_queue():
        calls["initialize"] += 1

    async def close_queue():
        calls["close"] += 1

    async def reconcile(**_kwargs):
        calls["reconcile"] += 1
        if mode == "reconcile_failure":
            if calls["reconcile"] >= 2:
                event_holder["event"].set()
            raise RuntimeError("reconciliation unavailable")
        return 0

    monkeypatch.setattr(module, "initialize_queue", initialize_queue)
    monkeypatch.setattr(module, "close_queue", close_queue)
    monkeypatch.setattr(module, "reconcile_outcome_unknown_once", reconcile)

    real_event = asyncio.Event
    event_holder = {}

    def event_factory():
        event_holder["event"] = real_event()
        return event_holder["event"]

    monkeypatch.setattr(module.asyncio, "Event", event_factory)

    class FakeHybridWorker:
        def __init__(self, **kwargs):
            self.registration = kwargs["registration"]
            self.handlers = kwargs["handlers"]

        async def run_once(self):
            if mode == "run_once_failure" and not calls.get("failed_once"):
                calls["failed_once"] = True
                raise RuntimeError("one transient loop failure")
            if mode in {"heartbeat_stop", "heartbeat_failure", "reconcile_failure"}:
                return False
            await asyncio.sleep(0)
            event_holder["event"].set()
            return True

    monkeypatch.setattr(module, "HybridWorker", FakeHybridWorker)
    return pool, store, calls, event_holder


@pytest.mark.asyncio
async def test_worker_process_starts_registers_runs_and_shuts_down_gracefully(monkeypatch):
    worker_settings(monkeypatch)
    pool, store, calls, event_holder = install_worker_fakes(monkeypatch)
    await module.run_worker()
    assert pool.closed is True
    assert store.heartbeat_calls == 1
    assert store.deregister_calls == [
        {"tenant_id": "tenant-test", "worker_id": "notebook-worker-test"}
    ]
    assert calls["initialize"] == 1
    assert calls["close"] == 1
    assert calls["reconcile"] == 1
    assert event_holder["event"].is_set()


@pytest.mark.asyncio
async def test_worker_process_rejects_disabled_mode_before_connecting(monkeypatch):
    worker_settings(monkeypatch, workflow_worker_enabled=False)
    with pytest.raises(RuntimeError, match="WORKFLOW_WORKER_ENABLED=true"):
        await module.run_worker()


@pytest.mark.asyncio
async def test_worker_process_closes_pool_when_database_role_is_invalid(monkeypatch):
    worker_settings(monkeypatch)
    pool, store, calls, _events = install_worker_fakes(
        monkeypatch,
        role=role_row(api_runtime_role_member=True),
    )
    with pytest.raises(RuntimeError, match="distinct, non-owner, NOBYPASSRLS"):
        await module.run_worker()
    assert pool.closed is True
    assert store.deregister_calls == []
    assert calls["initialize"] == 0
    assert calls["close"] == 0


@pytest.mark.asyncio
async def test_worker_process_cleans_up_when_initial_registry_heartbeat_fails(monkeypatch):
    worker_settings(monkeypatch)
    pool, store, calls, _events = install_worker_fakes(
        monkeypatch,
        mode="initial_heartbeat_failure",
    )
    with pytest.raises(RuntimeError, match="registry unavailable"):
        await module.run_worker()
    assert pool.closed is True
    assert store.deregister_calls == []
    assert calls["initialize"] == 1
    assert calls["close"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["heartbeat_stop", "heartbeat_failure", "reconcile_failure"])
async def test_worker_process_stops_on_heartbeat_or_reconciliation_failure(monkeypatch, mode):
    worker_settings(
        monkeypatch,
        workflow_worker_heartbeat_seconds=1,
        workflow_worker_poll_seconds=0.005,
    )
    pool, store, calls, event_holder = install_worker_fakes(monkeypatch, mode=mode)
    await module.run_worker()
    assert pool.closed is True
    assert event_holder["event"].is_set()
    assert store.deregister_calls
    assert calls["close"] == 1
    assert calls["reconcile"] >= 1


@pytest.mark.asyncio
async def test_worker_process_recovers_from_one_iteration_failure(monkeypatch):
    worker_settings(monkeypatch, workflow_worker_heartbeat_seconds=10)
    pool, store, calls, event_holder = install_worker_fakes(
        monkeypatch,
        mode="run_once_failure",
    )
    await module.run_worker()
    assert pool.closed is True
    assert calls["reconcile"] >= 2
    assert event_holder["event"].is_set()
    assert store.deregister_calls


def test_worker_main_configures_logging_and_runs_async_entrypoint(monkeypatch):
    calls = []
    monkeypatch.setattr(module, "configure_logging", lambda: calls.append("logging"))
    monkeypatch.setattr(module.asyncio, "run", lambda coroutine: (calls.append("run"), coroutine.close()))
    async def fake_run_worker():
        return None
    monkeypatch.setattr(module, "run_worker", fake_run_worker)
    module.main()
    assert calls == ["logging", "run"]

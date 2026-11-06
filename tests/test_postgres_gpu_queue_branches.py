from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest

from app.services.model_registry_errors import ModelRegistryConflictError
from app.services.postgres_gpu_queue import PostgresExternalGPUQueue
from app.workers.schemas import WorkerPlatform


class AsyncContext:
    def __init__(self, value=None):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *_args):
        return False


class FakeConnection:
    def __init__(self, pool):
        self.pool = pool

    def transaction(self):
        return AsyncContext()

    async def execute(self, query, *args):
        self.pool.executed.append((query, args))
        return self.pool.execute_result

    async def fetchrow(self, query, *args):
        self.pool.fetchrow_calls.append((query, args))
        if self.pool.rows:
            return self.pool.rows.pop(0)
        return None

    async def fetchval(self, query, *args):
        self.pool.fetchval_calls.append((query, args))
        if self.pool.scalars:
            return self.pool.scalars.pop(0)
        return self.pool.scalar


class FakePool:
    def __init__(self, *, rows=(), scalars=(), scalar=0, execute_result="UPDATE 0"):
        self.rows = list(rows)
        self.scalars = list(scalars)
        self.scalar = scalar
        self.execute_result = execute_result
        self.executed = []
        self.fetchrow_calls = []
        self.fetchval_calls = []
        self.connection = FakeConnection(self)
        self.closed = False

    def acquire(self):
        return AsyncContext(self.connection)

    async def fetchrow(self, query, *args):
        return await self.connection.fetchrow(query, *args)

    async def fetchval(self, query, *args):
        return await self.connection.fetchval(query, *args)

    async def execute(self, query, *args):
        return await self.connection.execute(query, *args)

    async def close(self):
        self.closed = True


def queue_with_pool(pool):
    queue = PostgresExternalGPUQueue("postgresql://test:test@localhost/test")
    queue._pool = pool
    return queue


def worker_row(**overrides):
    row = {
        "worker_id": "worker-a",
        "platform": "colab",
        "status": "active",
        "revoked_at": None,
        "token_expires_at": "2099-01-01T00:00:00Z",
        "capacity": 1,
        "supported_tasks": ["image_to_3d"],
        "gpu_vram_gb": 24,
        "available_gpu_memory_gb": 20,
        "available_memory_gb": 32,
    }
    row.update(overrides)
    return row


def job_row():
    return {
        "job_id": "job-a",
        "platform": "colab",
        "task": "image_to_3d",
        "status": "running",
        "input_asset": "asset://input.png",
        "prompt": None,
        "model_id": "org/model",
        "model_revision": "a" * 40,
        "options": {},
        "min_gpu_vram_gb": 8,
        "min_memory_gb": 8,
        "attempts": 1,
        "worker_id": "worker-a",
        "lease_expires_at": None,
        "next_attempt_at": None,
        "output_asset": None,
        "result_metadata": {},
        "idempotency_key": None,
        "error": None,
    }


def test_queue_open_is_idempotent_and_close_is_safe(monkeypatch):
    pool = FakePool(scalar=True)
    calls = 0

    async def create_pool(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return pool

    monkeypatch.setitem(sys.modules, "asyncpg", SimpleNamespace(create_pool=create_pool))
    queue = PostgresExternalGPUQueue("postgresql://test:test@localhost/test")
    asyncio.run(queue.open())
    asyncio.run(queue.open())
    assert calls == 1
    asyncio.run(queue.close())
    asyncio.run(queue.close())
    assert pool.closed is True


def test_queue_open_fails_clearly_when_asyncpg_is_not_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "asyncpg", None)
    queue = PostgresExternalGPUQueue("postgresql://test:test@localhost/test")
    with pytest.raises(RuntimeError, match="requires asyncpg"):
        asyncio.run(queue.open())


def test_queue_json_decoding_accepts_json_text_and_mapping_values():
    assert PostgresExternalGPUQueue._decode_json('{"seed":42}') == {"seed": 42}
    assert PostgresExternalGPUQueue._decode_json({"seed": 42}) == {"seed": 42}
    assert PostgresExternalGPUQueue._decode_json(None) == {}


def test_claim_returns_none_when_no_queued_job_is_available():
    pool = FakePool(rows=[None])
    queue = queue_with_pool(pool)
    assert asyncio.run(queue.claim(WorkerPlatform.COLAB, "worker-a")) is None
    assert len(pool.executed) == 1


def test_claim_for_worker_returns_none_for_missing_worker_or_full_capacity():
    missing_worker = queue_with_pool(FakePool(rows=[None]))
    assert asyncio.run(missing_worker.claim_for_worker("missing-worker")) is None

    full = queue_with_pool(
        FakePool(rows=[worker_row()], scalars=[1])
    )
    assert asyncio.run(full.claim_for_worker("worker-a")) is None


def test_claim_for_worker_decodes_task_list_and_enforces_model_registry(monkeypatch):
    pool = FakePool(
        rows=[
            worker_row(supported_tasks='["image_to_3d"]'),
            None,
        ],
        scalars=[0],
    )
    queue = queue_with_pool(pool)
    assert asyncio.run(
        queue.claim_for_worker("worker-a", enforce_model_registry=True)
    ) is None
    # One statement reclaims expired leases and another rejects unapproved model revisions.
    assert len(pool.executed) == 2
    assert "model_registry_versions" in pool.executed[1][0]
    assert len(pool.fetchrow_calls) == 2


def test_claim_for_worker_returns_none_for_worker_without_task_capabilities():
    pool = FakePool(rows=[worker_row(supported_tasks=[])], scalars=[0])
    queue = queue_with_pool(pool)
    assert asyncio.run(queue.claim_for_worker("worker-a")) is None
    assert len(pool.fetchrow_calls) == 1


def test_worker_heartbeat_and_cancel_return_none_for_stale_or_missing_rows():
    pool = FakePool(rows=[None, None, None, None])
    queue = queue_with_pool(pool)
    assert asyncio.run(queue.heartbeat("job-a", "worker-a")) is None
    assert asyncio.run(queue.complete("job-a", "worker-a", "asset://output.glb")) is None
    assert asyncio.run(queue.fail("job-a", "worker-a", "failure")) is None
    assert asyncio.run(queue.cancel("job-a")) is None


def test_model_registration_conflict_is_not_reported_as_success():
    pool = FakePool(rows=[None])
    queue = queue_with_pool(pool)
    request = SimpleNamespace(
        model_id="org/model",
        revision="a" * 40,
        model_name="Test Model",
        family="image_to_3d",
        source="huggingface",
        license_id="Apache-2.0",
        intended_use="CI test",
        input_schema={},
        output_schema={},
        hardware_requirements={},
        runtime_dependencies={},
        license_review_status="pending",
        validation_status="pending",
        evaluation_results={},
    )
    with pytest.raises(ModelRegistryConflictError):
        asyncio.run(queue.register_model_version(request))

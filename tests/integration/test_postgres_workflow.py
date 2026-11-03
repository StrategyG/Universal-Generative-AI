from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest

from ugai_workflow import (
    IdempotencyConflict,
    LeaseIdentity,
    LeaseLost,
    PostgresWorkflowStore,
    RetryScheduler,
    RetrySchedulerRegistration,
    TaskNotFound,
    TaskState,
)

ADMIN_DSN = os.getenv("UGAI_WORKFLOW_TEST_ADMIN_URL")
RUNTIME_DSN = os.getenv("UGAI_WORKFLOW_TEST_RUNTIME_URL")


@pytest.fixture(scope="session")
async def workflow_database():
    if not ADMIN_DSN or not RUNTIME_DSN:
        pytest.skip("isolated PostgreSQL workflow service is not configured")

    admin = await asyncpg.connect(ADMIN_DSN)
    runtime_pool = None
    try:
        # The CI database is disposable. Supabase roles are created only here so
        # the same private-schema blueprint can be exercised on vanilla Postgres.
        await admin.execute("CREATE ROLE anon NOLOGIN")
        await admin.execute("CREATE ROLE authenticated NOLOGIN")
        await admin.execute("CREATE ROLE service_role NOLOGIN BYPASSRLS")
        root = Path(__file__).resolve().parents[2]
        blueprint = (
            root / "docs" / "architecture" / "ugai-workflow-schema-blueprint.sql"
        ).read_text(encoding="utf-8")
        await admin.execute(blueprint)
        await admin.execute(
            "CREATE ROLE ugai_workflow_test LOGIN PASSWORD 'workflow-test-only'"
        )
        await admin.execute(
            "GRANT ugai_workflow_runtime TO ugai_workflow_test"
        )
        runtime_pool = await asyncpg.create_pool(
            RUNTIME_DSN, min_size=1, max_size=12, command_timeout=10
        )
        yield runtime_pool, admin
    finally:
        if runtime_pool is not None:
            await runtime_pool.close()
        await admin.close()


def new_task_args(*, tenant_id: str, actor_id: str = "integration-actor", suffix: str):
    return {
        "tenant_id": tenant_id,
        "actor_id": actor_id,
        "task_type": "integration_work",
        "idempotency_key": f"test-{suffix}",
        "input_digest": "a" * 64,
        "metadata": {"request_ref": f"test://{suffix}"},
        "max_retries": 2,
    }


@pytest.mark.asyncio
async def test_database_enforces_tenant_rls_and_idempotency(workflow_database) -> None:
    pool, _admin = workflow_database
    store = PostgresWorkflowStore(pool)
    tenant = f"tenant-{uuid4()}"
    args = new_task_args(tenant_id=tenant, suffix=str(uuid4()))

    first = await store.create_task(**args)
    repeated = await store.create_task(**args)
    assert repeated.task_id == first.task_id

    with pytest.raises(IdempotencyConflict):
        await store.create_task(**{**args, "input_digest": "b" * 64})

    with pytest.raises(TaskNotFound):
        await store.get_task(task_id=first.task_id, tenant_id=f"other-{uuid4()}")


@pytest.mark.asyncio
async def test_skip_locked_claims_are_unique_under_concurrency(workflow_database) -> None:
    pool, _admin = workflow_database
    store = PostgresWorkflowStore(pool)
    tenant = f"tenant-{uuid4()}"
    for index in range(12):
        await store.create_task(
            **new_task_args(tenant_id=tenant, suffix=f"{uuid4()}-{index}")
        )

    claims = await asyncio.gather(
        *(
            store.claim_next(
                tenant_id=tenant,
                worker_id=f"worker-{index}",
                supported_task_types=("integration_work",),
                lease_seconds=30,
            )
            for index in range(12)
        )
    )
    assert all(claim is not None for claim in claims)
    task_ids = [claim.task_id for claim in claims if claim is not None]
    assert len(task_ids) == len(set(task_ids)) == 12
    assert len({claim.lease_token for claim in claims if claim is not None}) == 12


@pytest.mark.asyncio
async def test_expired_lease_is_refenced_and_old_worker_is_rejected(workflow_database) -> None:
    pool, admin = workflow_database
    store = PostgresWorkflowStore(pool)
    tenant = f"tenant-{uuid4()}"
    task = await store.create_task(
        **new_task_args(tenant_id=tenant, suffix=str(uuid4()))
    )
    first = await store.claim_next(
        tenant_id=tenant,
        worker_id="worker-old",
        supported_task_types=("integration_work",),
        lease_seconds=5,
    )
    assert first is not None

    await admin.execute(
        """
        UPDATE ugai_workflow.tasks
        SET lease_expires_at = clock_timestamp() - interval '1 second'
        WHERE task_id = $1
        """,
        task.task_id,
    )
    second = await store.claim_next(
        tenant_id=tenant,
        worker_id="worker-new",
        supported_task_types=("integration_work",),
        lease_seconds=30,
    )
    assert second is not None
    assert second.task_id == first.task_id
    assert second.lease_token != first.lease_token

    with pytest.raises(LeaseLost):
        await store.heartbeat(
            task_id=task.task_id,
            tenant_id=tenant,
            lease=LeaseIdentity("worker-old", first.lease_token),
            lease_seconds=30,
        )


@pytest.mark.asyncio
async def test_retry_scheduler_requeues_only_due_retryable_failures(workflow_database) -> None:
    pool, admin = workflow_database
    store = PostgresWorkflowStore(pool)
    tenant = f"tenant-{uuid4()}"
    task = await store.create_task(
        **new_task_args(tenant_id=tenant, suffix=str(uuid4()))
    )
    claimed = await store.claim_next(
        tenant_id=tenant,
        worker_id="worker-retry",
        supported_task_types=("integration_work",),
        lease_seconds=30,
    )
    assert claimed is not None
    failed = await store.transition(
        task_id=task.task_id,
        tenant_id=tenant,
        expected_version=claimed.version,
        target=TaskState.FAILED,
        actor_id=claimed.actor_id,
        reason_code="transient_provider_error",
        lease=LeaseIdentity("worker-retry", claimed.lease_token),
        retryable=True,
        error_code="provider_timeout",
    )
    assert failed.retryable is True

    scheduler = RetryScheduler(
        store=store,
        registration=RetrySchedulerRegistration(
            scheduler_id="integration-retry-scheduler",
            tenant_id=tenant,
            batch_size=10,
            poll_interval_seconds=1,
        ),
    )
    assert await scheduler.run_once() == 0

    await admin.execute(
        """
        UPDATE ugai_workflow.tasks
        SET available_at = clock_timestamp() - interval '1 second'
        WHERE task_id = $1
        """,
        task.task_id,
    )
    assert await scheduler.run_once() == 1
    recovered = await store.get_task(task_id=task.task_id, tenant_id=tenant)
    assert recovered.state is TaskState.RECEIVED
    assert recovered.retry_count == 1
    assert recovered.retryable is False
    assert await scheduler.run_once() == 0

    events = await admin.fetch(
        """
        SELECT event_type FROM ugai_workflow.events
        WHERE task_id = $1 ORDER BY task_version, created_at
        """,
        task.task_id,
    )
    assert "retry_scheduled" in {row["event_type"] for row in events}

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit
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
    TaskResultConflict,
    TaskState,
)

ADMIN_DSN = os.getenv("UGAI_WORKFLOW_TEST_ADMIN_URL")
RUNTIME_DSN = os.getenv("UGAI_WORKFLOW_TEST_RUNTIME_URL")


@pytest.fixture(scope="function")
async def workflow_database():
    if not ADMIN_DSN or not RUNTIME_DSN:
        pytest.skip("isolated PostgreSQL workflow service is not configured")

    # asyncpg resources must be created and closed on the same event loop as the
    # test using them. Function scope also prevents pool objects crossing loops.
    admin = await asyncpg.connect(ADMIN_DSN)
    runtime_pool = None
    try:
        async def ensure_role(name: str, ddl: str) -> None:
            exists = await admin.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = $1)", name
            )
            if not exists:
                await admin.execute(ddl)

        # These Supabase roles exist only in this disposable CI database.
        await ensure_role("anon", "CREATE ROLE anon NOLOGIN")
        await ensure_role("authenticated", "CREATE ROLE authenticated NOLOGIN")
        await ensure_role(
            "service_role", "CREATE ROLE service_role NOLOGIN BYPASSRLS"
        )

        schema_exists = await admin.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'ugai_workflow')"
        )
        if not schema_exists:
            root = Path(__file__).resolve().parents[2]
            migrations = root / "postgres" / "migrations"
            # Use the exact ordered workflow runtime migrations used for deployment.
            # A blueprint is not executable migration evidence.
            for migration_name in (
                "0003_ugai_workflow_runtime.sql",
                "0004_ugai_task_api_contract.sql",
                "0005_ugai_workflow_outcome_unknown.sql",
                "0006_ugai_notebook_worker_results.sql",
            ):
                await admin.execute(
                    (migrations / migration_name).read_text(encoding="utf-8")
                )

        await ensure_role(
            "ugai_workflow_test",
            "CREATE ROLE ugai_workflow_test LOGIN PASSWORD 'workflow-test-only'",
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


@pytest.fixture(scope="function")
async def workflow_worker_pool(workflow_database):
    """Create a distinct login that can assume only the worker group role."""
    _runtime_pool, admin = workflow_database
    login = "ugai_workflow_worker_test"
    password = "worker-test-only"
    exists = await admin.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = $1)", login
    )
    if not exists:
        await admin.execute(
            f"CREATE ROLE {login} LOGIN PASSWORD '{password}' NOBYPASSRLS"
        )
    else:
        await admin.execute(
            f"ALTER ROLE {login} WITH LOGIN PASSWORD '{password}' NOBYPASSRLS"
        )
    await admin.execute(f"GRANT ugai_workflow_worker TO {login}")
    parts = urlsplit(RUNTIME_DSN)
    host = parts.hostname or "localhost"
    if parts.port:
        host = f"{host}:{parts.port}"
    netloc = f"{quote(login)}:{quote(password)}@{host}"
    worker_dsn = urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    pool = await asyncpg.create_pool(worker_dsn, min_size=1, max_size=4, command_timeout=10)
    try:
        yield pool
    finally:
        await pool.close()


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

    # Prove the runtime database role is not privileged and that row visibility
    # is enforced by PostgreSQL RLS itself, not only by an application WHERE clause.
    async with pool.acquire() as connection:
        role = await connection.fetchrow(
            """
            SELECT r.rolsuper, r.rolbypassrls,
                   pg_get_userbyid(c.relowner) = current_user AS owns_tasks
            FROM pg_roles r
            CROSS JOIN pg_class c
            WHERE r.rolname = current_user
              AND c.oid = 'ugai_workflow.tasks'::regclass
            """
        )
        assert role is not None
        assert role["rolsuper"] is False
        assert role["rolbypassrls"] is False
        assert role["owns_tasks"] is False
        async with connection.transaction():
            await connection.fetchval(
                "SELECT set_config('app.ugai_tenant_id', $1, true)",
                f"other-{uuid4()}",
            )
            visible = await connection.fetchval(
                "SELECT count(*) FROM ugai_workflow.tasks WHERE task_id = $1",
                first.task_id,
            )
            assert visible == 0

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
        WHERE task_id = $1 ORDER BY task_version, occurred_at
        """,
        task.task_id,
    )
    assert "retry_scheduled" in {row["event_type"] for row in events}



@pytest.mark.asyncio
async def test_decision_approval_reference_and_digests_are_durable(workflow_database) -> None:
    pool, _admin = workflow_database
    store = PostgresWorkflowStore(pool)
    tenant = f"tenant-{uuid4()}"
    task = await store.create_task(
        **new_task_args(tenant_id=tenant, suffix=str(uuid4()))
    )

    async def advance(expected_state, next_state, worker_id):
        claimed = await store.claim_next(
            tenant_id=tenant,
            worker_id=worker_id,
            supported_task_types=("integration_work",),
            lease_seconds=30,
        )
        assert claimed is not None
        assert claimed.state is expected_state
        return await store.transition(
            task_id=task.task_id,
            tenant_id=tenant,
            expected_version=claimed.version,
            target=next_state,
            actor_id=claimed.actor_id,
            reason_code=f"advance_{next_state.value}",
            lease=LeaseIdentity(worker_id, claimed.lease_token),
        )

    await advance(TaskState.RECEIVED, TaskState.OBSERVING, "decision-worker-1")
    await advance(TaskState.OBSERVING, TaskState.PLANNING, "decision-worker-2")
    approval_reference = "approval-ref-opaque-0001"
    decision_digest = "c" * 64
    plan_digest = "d" * 64
    # The approval transition writes only opaque references and SHA-256 digests.
    claimed = await store.claim_next(
        tenant_id=tenant,
        worker_id="decision-worker-3",
        supported_task_types=("integration_work",),
        lease_seconds=30,
    )
    assert claimed is not None
    assert claimed.state is TaskState.PLANNING
    awaited = await store.transition(
        task_id=task.task_id,
        tenant_id=tenant,
        expected_version=claimed.version,
        target=TaskState.AWAITING_APPROVAL,
        actor_id=claimed.actor_id,
        reason_code="decision_approval_requested",
        lease=LeaseIdentity("decision-worker-3", claimed.lease_token),
        approval_reference=approval_reference,
        decision_digest=decision_digest,
        plan_digest=plan_digest,
    )
    persisted = await store.get_task(task_id=task.task_id, tenant_id=tenant)
    assert awaited.state is TaskState.AWAITING_APPROVAL
    assert persisted.approval_reference == approval_reference
    assert persisted.decision_digest == decision_digest
    assert persisted.plan_digest == plan_digest


@pytest.mark.asyncio
async def test_expired_execution_lease_is_quarantined_not_replayed(workflow_database) -> None:
    pool, admin = workflow_database
    store = PostgresWorkflowStore(pool)
    tenant = f"tenant-{uuid4()}"
    task = await store.create_task(
        **new_task_args(tenant_id=tenant, suffix=str(uuid4()))
    )

    async def advance(target: TaskState, worker_id: str) -> None:
        claimed = await store.claim_next(
            tenant_id=tenant,
            worker_id=worker_id,
            supported_task_types=("integration_work",),
            lease_seconds=30,
        )
        assert claimed is not None
        await store.transition(
            task_id=task.task_id,
            tenant_id=tenant,
            expected_version=claimed.version,
            target=target,
            actor_id=claimed.actor_id,
            reason_code=f"advance_{target.value}",
            lease=LeaseIdentity(worker_id, claimed.lease_token),
        )

    await advance(TaskState.OBSERVING, "quarantine-1")
    await advance(TaskState.PLANNING, "quarantine-2")
    await advance(TaskState.EXECUTING, "quarantine-3")
    # The transition into EXECUTING releases the planning lease. Claim once
    # more so the test expires a genuine in-flight execution lease.
    executing = await store.claim_next(
        tenant_id=tenant,
        worker_id="quarantine-execution-worker",
        supported_task_types=("integration_work",),
        lease_seconds=30,
    )
    assert executing is not None
    assert executing.state is TaskState.EXECUTING
    await admin.execute(
        """
        UPDATE ugai_workflow.tasks
        SET lease_expires_at = clock_timestamp() - interval '1 second'
        WHERE task_id = $1
        """,
        task.task_id,
    )

    replay = await store.claim_next(
        tenant_id=tenant,
        worker_id="quarantine-replay-attempt",
        supported_task_types=("integration_work",),
        lease_seconds=30,
    )
    quarantined = await store.get_task(task_id=task.task_id, tenant_id=tenant)
    assert replay is None
    assert quarantined.state is TaskState.OUTCOME_UNKNOWN
    assert quarantined.retryable is False

    events = await admin.fetch(
        """
        SELECT event_type, from_state, to_state
        FROM ugai_workflow.events
        WHERE task_id = $1
        ORDER BY event_id
        """,
        task.task_id,
    )
    assert any(
        event["event_type"] == "execution_lease_expired"
        and event["from_state"] == "executing"
        and event["to_state"] == "outcome_unknown"
        for event in events
    )

    with pytest.raises(PermissionError, match="reconciliation_evidence_required"):
        await store.transition(
            task_id=task.task_id,
            tenant_id=tenant,
            expected_version=quarantined.version,
            target=TaskState.VERIFYING,
            actor_id="system:result-reconciler",
            reason_code="result_reconciliation",
            require_lease=False,
        )
    with pytest.raises(Exception):
        await store.transition(
            task_id=task.task_id,
            tenant_id=tenant,
            expected_version=quarantined.version,
            target=TaskState.OBSERVING,
            actor_id="operator-1",
            reason_code="operator_override",
            require_lease=False,
            operator_override=True,
        )

    reconciled = await store.transition(
        task_id=task.task_id,
        tenant_id=tenant,
        expected_version=quarantined.version,
        target=TaskState.VERIFYING,
        actor_id="system:result-reconciler",
        reason_code="result_reconciled",
        require_lease=False,
        reconciliation_verified=True,
        metadata={"evidence_digest": "e" * 64},
    )
    assert reconciled.state is TaskState.VERIFYING


@pytest.mark.asyncio
async def test_worker_role_is_separate_and_results_are_immutable_and_tenant_scoped(
    workflow_database, workflow_worker_pool
) -> None:
    api_pool, _admin = workflow_database
    api_store = PostgresWorkflowStore(api_pool)
    worker_store = PostgresWorkflowStore(workflow_worker_pool)
    tenant = f"tenant-{uuid4()}"
    task = await api_store.create_task(
        **{
            **new_task_args(tenant_id=tenant, suffix=str(uuid4())),
            "project_id": "project-a",
        }
    )

    identity = await workflow_worker_pool.fetchrow(
        """
        SELECT current_user AS login,
               pg_has_role(current_user, 'ugai_workflow_worker', 'member') AS worker_member,
               pg_has_role(current_user, 'ugai_workflow_runtime', 'member') AS api_member,
               rolsuper, rolbypassrls
        FROM pg_roles WHERE rolname = current_user
        """
    )
    assert identity["login"] == "ugai_workflow_worker_test"
    assert identity["worker_member"] is True
    assert identity["api_member"] is False
    assert identity["rolsuper"] is False
    assert identity["rolbypassrls"] is False

    assert await api_store.has_healthy_worker(
        tenant_id=tenant, task_type="notebook_task"
    ) is False
    await worker_store.heartbeat_worker(
        tenant_id=tenant,
        worker_id="notebook-worker-integration",
        task_types=("notebook_task",),
    )
    assert await api_store.has_healthy_worker(
        tenant_id=tenant, task_type="notebook_task"
    ) is True

    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await api_store.heartbeat_worker(
            tenant_id=tenant,
            worker_id="api-must-not-register-worker",
            task_types=("notebook_task",),
        )

    ciphertext = b"encrypted-result-ciphertext"
    digest = "a" * 64
    assert await worker_store.put_encrypted_result(
        tenant_id=tenant,
        actor_id=task.actor_id,
        project_id="project-a",
        task_id=task.task_id,
        key_id="test-v1",
        ciphertext=ciphertext,
        payload_sha256=digest,
    ) == digest
    assert await worker_store.put_encrypted_result(
        tenant_id=tenant,
        actor_id=task.actor_id,
        project_id="project-a",
        task_id=task.task_id,
        key_id="test-v1",
        ciphertext=ciphertext,
        payload_sha256=digest,
    ) == digest
    with pytest.raises(TaskResultConflict):
        await worker_store.put_encrypted_result(
            tenant_id=tenant,
            actor_id=task.actor_id,
            project_id="project-a",
            task_id=task.task_id,
            key_id="test-v1",
            ciphertext=ciphertext,
            payload_sha256="b" * 64,
        )

    stored = await api_store.get_encrypted_result(
        tenant_id=tenant, task_id=task.task_id
    )
    assert stored == ("test-v1", ciphertext, digest)
    assert await api_store.get_encrypted_result(
        tenant_id=f"other-{uuid4()}", task_id=task.task_id
    ) is None

    await worker_store.deregister_worker(
        tenant_id=tenant, worker_id="notebook-worker-integration"
    )
    assert await api_store.has_healthy_worker(
        tenant_id=tenant, task_type="notebook_task"
    ) is False

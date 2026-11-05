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
from app.workflow_runtime import _assert_restricted_runtime_role

from ugai_workflow.input_vault import (
    WorkflowInputConflict,
    WorkflowInputNotFound,
    WorkflowInputVault,
)
from ugai_workflow.result_vault import WorkflowResultConflict, WorkflowResultVault

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
            migration = (
                root / "postgres" / "migrations" / "0003_ugai_workflow_runtime.sql"
            ).read_text(encoding="utf-8")
            await admin.execute(migration)

        input_table_exists = await admin.fetchval(
            """
            SELECT EXISTS (
                SELECT 1 FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'ugai_workflow' AND c.relname = 'inputs'
            )
            """
        )
        if not input_table_exists:
            root = Path(__file__).resolve().parents[2]
            migration = (
                root / "postgres" / "migrations" / "0004_ugai_workflow_encrypted_inputs.sql"
            ).read_text(encoding="utf-8")
            await admin.execute(migration)

        for table_name, migration_name in (
            ("results", "0005_ugai_workflow_encrypted_results.sql"),
            ("workers", "0006_ugai_workflow_worker_registry.sql"),
            ("workspace_bindings", "0007_ugai_workflow_workspace_bindings.sql"),
        ):
            table_exists = await admin.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'ugai_workflow' AND c.relname = $1
                )
                """,
                table_name,
            )
            if not table_exists:
                root = Path(__file__).resolve().parents[2]
                migration = (root / "postgres" / "migrations" / migration_name).read_text(
                    encoding="utf-8"
                )
                await admin.execute(migration)

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
    await _assert_restricted_runtime_role(pool)
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
async def test_expired_execution_lease_is_quarantined_not_reclaimed(workflow_database) -> None:
    pool, admin = workflow_database
    store = PostgresWorkflowStore(pool)
    tenant = f"tenant-{uuid4()}"
    executing_task = await store.create_task(
        **new_task_args(tenant_id=tenant, suffix=str(uuid4()))
    )
    first_lease = await store.claim_next(
        tenant_id=tenant,
        worker_id="worker-side-effect",
        supported_task_types=("integration_work",),
        lease_seconds=30,
    )
    assert first_lease is not None
    assert first_lease.task_id == executing_task.task_id

    pending_task = await store.create_task(
        **new_task_args(tenant_id=tenant, suffix=str(uuid4()))
    )
    await admin.execute(
        """
        UPDATE ugai_workflow.tasks
        SET state = 'executing',
            lease_expires_at = clock_timestamp() - interval '1 second'
        WHERE task_id = $1
        """,
        executing_task.task_id,
    )

    next_claim = await store.claim_next(
        tenant_id=tenant,
        worker_id="worker-next",
        supported_task_types=("integration_work",),
        lease_seconds=30,
    )
    assert next_claim is not None
    assert next_claim.task_id == pending_task.task_id

    quarantined = await store.get_task(task_id=executing_task.task_id, tenant_id=tenant)
    assert quarantined.state is TaskState.OUTCOME_UNKNOWN
    assert quarantined.lease_token is None
    assert quarantined.retryable is False
    assert quarantined.error_code == "outcome_unknown"

    event = await admin.fetchrow(
        """
        SELECT event_type, from_state, to_state, details
        FROM ugai_workflow.events
        WHERE task_id = $1
        ORDER BY event_id DESC
        LIMIT 1
        """,
        executing_task.task_id,
    )
    assert event is not None
    assert event["event_type"] == "execution_lease_expired"
    assert event["from_state"] == "executing"
    assert event["to_state"] == "outcome_unknown"

    with pytest.raises(LeaseLost):
        await store.heartbeat(
            task_id=executing_task.task_id,
            tenant_id=tenant,
            lease=LeaseIdentity("worker-side-effect", first_lease.lease_token),
            lease_seconds=30,
        )


@pytest.mark.asyncio
async def test_unknown_outcome_requires_verified_evidence_for_reconciliation(workflow_database) -> None:
    pool, _admin = workflow_database
    store = PostgresWorkflowStore(pool)
    tenant = f"tenant-{uuid4()}"
    task = await store.create_task(**new_task_args(tenant_id=tenant, suffix=str(uuid4())))
    # Move through the same initial state transition used by the worker.
    claimed = await store.claim_next(
        tenant_id=tenant,
        worker_id="worker-uncertain",
        supported_task_types=("integration_work",),
        lease_seconds=30,
    )
    assert claimed is not None
    claimed = await store.transition(
        task_id=task.task_id,
        tenant_id=tenant,
        expected_version=claimed.version,
        target=TaskState.OBSERVING,
        actor_id=claimed.actor_id,
        reason_code="observed",
        lease=LeaseIdentity("worker-uncertain", claimed.lease_token),
    )
    claimed = await store.claim_next(
        tenant_id=tenant,
        worker_id="worker-uncertain",
        supported_task_types=("integration_work",),
        lease_seconds=30,
    )
    assert claimed is not None
    claimed = await store.transition(
        task_id=task.task_id,
        tenant_id=tenant,
        expected_version=claimed.version,
        target=TaskState.PLANNING,
        actor_id=claimed.actor_id,
        reason_code="planned",
        lease=LeaseIdentity("worker-uncertain", claimed.lease_token),
    )
    claimed = await store.claim_next(
        tenant_id=tenant,
        worker_id="worker-uncertain",
        supported_task_types=("integration_work",),
        lease_seconds=30,
    )
    assert claimed is not None
    claimed = await store.transition(
        task_id=task.task_id,
        tenant_id=tenant,
        expected_version=claimed.version,
        target=TaskState.EXECUTING,
        actor_id=claimed.actor_id,
        reason_code="execution_started",
        lease=LeaseIdentity("worker-uncertain", claimed.lease_token),
    )
    claimed = await store.claim_next(
        tenant_id=tenant,
        worker_id="worker-uncertain",
        supported_task_types=("integration_work",),
        lease_seconds=30,
    )
    assert claimed is not None
    uncertain = await store.transition(
        task_id=task.task_id,
        tenant_id=tenant,
        expected_version=claimed.version,
        target=TaskState.OUTCOME_UNKNOWN,
        actor_id=claimed.actor_id,
        reason_code="external_outcome_unknown",
        lease=LeaseIdentity("worker-uncertain", claimed.lease_token),
        error_code="outcome_unknown",
    )
    with pytest.raises(PermissionError, match="reconciliation_evidence_required"):
        await store.transition(
            task_id=task.task_id,
            tenant_id=tenant,
            expected_version=uncertain.version,
            target=TaskState.VERIFYING,
            actor_id="trusted-reconciler",
            reason_code="external_outcome_reconciled",
            require_lease=False,
            metadata={},
        )

    reconciled = await store.transition(
        task_id=task.task_id,
        tenant_id=tenant,
        expected_version=uncertain.version,
        target=TaskState.VERIFYING,
        actor_id="trusted-reconciler",
        reason_code="external_outcome_reconciled",
        require_lease=False,
        reconciliation_verified=True,
        metadata={"evidence_digest": "e" * 64},
    )
    assert reconciled.state is TaskState.VERIFYING


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
async def test_encrypted_result_vault_is_immutable_and_actor_scoped(workflow_database) -> None:
    pool, _admin = workflow_database
    store = PostgresWorkflowStore(pool)
    tenant = f"tenant-{uuid4()}"
    actor = "principal:" + "a" * 64
    task = await store.create_task(**new_task_args(
        tenant_id=tenant,
        actor_id=actor,
        suffix=str(uuid4()),
    ))
    key = bytes(range(32))
    vault = WorkflowResultVault(
        pool=pool,
        active_key_id="test-result-v1",
        keyring={"test-result-v1": key},
    )
    payload = {
        "task_id": str(task.task_id),
        "candidate_answer": "reviewable answer",
        "human_review_required": True,
    }
    digest = await vault.put(
        tenant_id=tenant,
        actor_id=actor,
        project_id="project-1",
        task_id=task.task_id,
        payload=payload,
    )
    repeated = await vault.put(
        tenant_id=tenant,
        actor_id=actor,
        project_id="project-1",
        task_id=task.task_id,
        payload=payload,
    )
    assert repeated == digest
    assert await vault.get(
        tenant_id=tenant,
        actor_id=actor,
        project_id="project-1",
        task_id=task.task_id,
    ) == payload

    with pytest.raises(WorkflowInputNotFound):
        await vault.get(
            tenant_id=tenant,
            actor_id="principal:" + "b" * 64,
            project_id="project-1",
            task_id=task.task_id,
        )
    with pytest.raises(WorkflowResultConflict):
        await vault.put(
            tenant_id=tenant,
            actor_id=actor,
            project_id="project-1",
            task_id=task.task_id,
            payload={**payload, "candidate_answer": "different answer"},
        )


@pytest.mark.asyncio
async def test_worker_registry_requires_fresh_tenant_scoped_heartbeat(workflow_database) -> None:
    pool, _admin = workflow_database
    store = PostgresWorkflowStore(pool)
    tenant = f"tenant-{uuid4()}"
    worker_id = f"notebook-worker-{uuid4()}"
    assert not await store.has_active_worker(
        tenant_id=tenant,
        task_type="notebook_request",
    )
    await store.register_worker(
        tenant_id=tenant,
        worker_id=worker_id,
        task_types=("notebook_request",),
    )
    assert await store.has_active_worker(
        tenant_id=tenant,
        task_type="notebook_request",
    )
    assert not await store.has_active_worker(
        tenant_id=tenant,
        task_type="decision_evaluation",
    )
    assert await store.heartbeat_worker(tenant_id=tenant, worker_id=worker_id)
    await store.deregister_worker(tenant_id=tenant, worker_id=worker_id)
    assert not await store.has_active_worker(
        tenant_id=tenant,
        task_type="notebook_request",
    )


@pytest.mark.asyncio
async def test_workspace_binding_is_tenant_project_scoped(workflow_database) -> None:
    pool, admin = workflow_database
    store = PostgresWorkflowStore(pool)
    tenant = f"tenant-{uuid4()}"
    workspace = uuid4()
    await admin.execute(
        """
        INSERT INTO ugai_workflow.workspace_bindings (
            tenant_id, workspace_id, project_id, status
        )
        VALUES ($1, $2, $3, 'active')
        """,
        tenant,
        workspace,
        "project-1",
    )
    assert await store.workspace_is_bound(
        tenant_id=tenant,
        workspace_id=workspace,
        project_id="project-1",
    )
    assert not await store.workspace_is_bound(
        tenant_id=tenant,
        workspace_id=workspace,
        project_id="project-2",
    )
    assert not await store.workspace_is_bound(
        tenant_id=f"other-{tenant}",
        workspace_id=workspace,
        project_id="project-1",
    )


@pytest.mark.asyncio
async def test_encrypted_input_vault_is_actor_scoped_and_idempotent(workflow_database) -> None:
    pool, admin = workflow_database
    tenant = f"tenant-{uuid4()}"
    actor = f"actor-{uuid4()}"
    project = f"project-{uuid4()}"
    workspace_id = uuid4()
    notebook_id = uuid4()
    vault = WorkflowInputVault(
        pool=pool,
        active_key_id="integration-key-v1",
        keyring={"integration-key-v1": bytes(range(32))},
    )
    payload = {
        "intent": "private notebook content must never be stored as plaintext",
        "workspace_id": str(workspace_id),
        "notebook_id": str(notebook_id),
        "requested_capabilities": ["reasoning.read"],
    }
    first = await vault.put(
        tenant_id=tenant,
        actor_id=actor,
        project_id=project,
        workspace_id=workspace_id,
        notebook_id=notebook_id,
        idempotency_key="input-idempotency-0001",
        payload=payload,
    )
    repeated = await vault.put(
        tenant_id=tenant,
        actor_id=actor,
        project_id=project,
        workspace_id=workspace_id,
        notebook_id=notebook_id,
        idempotency_key="input-idempotency-0001",
        payload=payload,
    )
    assert repeated.input_ref == first.input_ref
    assert repeated.input_digest == first.input_digest

    stored = await admin.fetchrow(
        """
        SELECT ciphertext, nonce, key_id, payload_digest
        FROM ugai_workflow.inputs WHERE input_ref = $1
        """,
        first.input_ref,
    )
    assert stored is not None
    assert stored["key_id"] == "integration-key-v1"
    assert stored["payload_digest"] == first.input_digest
    assert payload["intent"].encode("utf-8") not in stored["ciphertext"]

    resolved = await vault.resolve(
        input_ref=first.input_ref,
        tenant_id=tenant,
        actor_id=actor,
        expected_project_id=project,
    )
    assert resolved == payload

    with pytest.raises(WorkflowInputConflict):
        await vault.put(
            tenant_id=tenant,
            actor_id=actor,
            project_id=project,
            workspace_id=workspace_id,
            notebook_id=notebook_id,
            idempotency_key="input-idempotency-0001",
            payload={**payload, "intent": "different payload"},
        )

    with pytest.raises(WorkflowInputNotFound):
        await vault.get_metadata(
            input_ref=first.input_ref,
            tenant_id=tenant,
            actor_id="different-actor",
        )

    # PostgreSQL RLS itself hides the input from another actor in the same tenant.
    async with pool.acquire() as connection:
        async with connection.transaction():
            await connection.fetchval(
                "SELECT set_config('app.ugai_tenant_id', $1, true)", tenant
            )
            await connection.fetchval(
                "SELECT set_config('app.ugai_actor_id', $1, true)", "different-actor"
            )
            visible = await connection.fetchval(
                "SELECT count(*) FROM ugai_workflow.inputs WHERE input_ref = $1",
                first.input_ref,
            )
            assert visible == 0


@pytest.mark.asyncio
async def test_user_cannot_cancel_task_while_any_worker_lease_exists(workflow_database) -> None:
    pool, _admin = workflow_database
    store = PostgresWorkflowStore(pool)
    tenant = f"tenant-{uuid4()}"
    task = await store.create_task(
        **new_task_args(tenant_id=tenant, suffix=str(uuid4()))
    )
    claimed = await store.claim_next(
        tenant_id=tenant,
        worker_id="worker-cancellation-race",
        supported_task_types=("integration_work",),
        lease_seconds=30,
    )
    assert claimed is not None

    with pytest.raises(LeaseLost, match="worker_lease"):
        await store.transition(
            task_id=task.task_id,
            tenant_id=tenant,
            expected_version=claimed.version,
            target=TaskState.CANCELLED,
            actor_id=task.actor_id,
            reason_code="user_requested_cancel",
            require_lease=False,
        )

    # A queued task without a worker lease can still be cancelled safely.
    queued = await store.create_task(
        **new_task_args(tenant_id=tenant, suffix=str(uuid4()))
    )
    cancelled = await store.transition(
        task_id=queued.task_id,
        tenant_id=tenant,
        expected_version=queued.version,
        target=TaskState.CANCELLED,
        actor_id=queued.actor_id,
        reason_code="user_requested_cancel",
        require_lease=False,
    )
    assert cancelled.state is TaskState.CANCELLED


from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest

from app.tasks.payloads import EncryptedTaskPayload, TaskPayloadCipher, TaskPayloadIntegrityError
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

        root = Path(__file__).resolve().parents[2]
        blueprint = (
            root / "docs" / "architecture" / "ugai-workflow-schema-blueprint.sql"
        ).read_text(encoding="utf-8")
        # Re-apply the idempotent blueprint for every test. This exercises both
        # fresh creation and upgrade paths when a prior test created the schema.
        await admin.execute(blueprint)

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
async def test_encrypted_task_payload_is_atomic_tenant_scoped_and_idempotent(workflow_database) -> None:
    pool, admin = workflow_database
    store = PostgresWorkflowStore(pool)
    tenant = f"tenant-{uuid4()}"
    actor = "notebook-actor"
    idempotency_key = f"notebook-{uuid4()}"
    plaintext = b'{"intent":"private notebook content","workspace_id":"workspace-1"}'
    digest = hashlib.sha256(plaintext).hexdigest()
    cipher = TaskPayloadCipher(b"p" * 32, key_version="test-v1")
    first_task_id = uuid4()
    first_envelope = cipher.encrypt_bytes(
        plaintext, tenant_id=tenant, task_id=first_task_id
    )
    metadata = {
        "request_ref": f"notebook-task:{idempotency_key}",
        "correlation_id": idempotency_key,
        "schema_version": "1",
    }

    first = await store.create_task(
        tenant_id=tenant,
        actor_id=actor,
        task_type="notebook.request",
        idempotency_key=idempotency_key,
        input_digest=digest,
        task_id=first_task_id,
        metadata=metadata,
        encrypted_payload=first_envelope.ciphertext,
        payload_nonce=first_envelope.nonce,
        payload_key_version=first_envelope.key_version,
    )

    # A second request may use a new request ID and candidate task UUID, but the
    # stable idempotency key and digest must return the original durable task.
    retry_task_id = uuid4()
    retry_envelope = cipher.encrypt_bytes(
        plaintext, tenant_id=tenant, task_id=retry_task_id
    )
    repeated = await store.create_task(
        tenant_id=tenant,
        actor_id=actor,
        task_type="notebook.request",
        idempotency_key=idempotency_key,
        input_digest=digest,
        task_id=retry_task_id,
        metadata=metadata,
        encrypted_payload=retry_envelope.ciphertext,
        payload_nonce=retry_envelope.nonce,
        payload_key_version=retry_envelope.key_version,
    )
    assert repeated.task_id == first.task_id

    stored = await store.get_task_payload(task_id=first.task_id, tenant_id=tenant)
    assert plaintext not in stored.ciphertext
    decrypted = cipher.decrypt_bytes(
        EncryptedTaskPayload(
            ciphertext=stored.ciphertext,
            nonce=stored.nonce,
            key_version=stored.key_version,
        ),
        tenant_id=tenant,
        task_id=first.task_id,
    )
    assert decrypted == plaintext

    payload_count = await admin.fetchval(
        """
        SELECT count(*) FROM ugai_workflow.task_payloads
        WHERE tenant_id = $1 AND task_id = $2
        """,
        tenant,
        first.task_id,
    )
    assert payload_count == 1

    with pytest.raises(TaskNotFound):
        await store.get_task_payload(
            task_id=first.task_id, tenant_id=f"other-{uuid4()}"
        )

    with pytest.raises(TaskPayloadIntegrityError):
        cipher.decrypt_bytes(
            EncryptedTaskPayload(
                ciphertext=stored.ciphertext,
                nonce=stored.nonce,
                key_version=stored.key_version,
            ),
            tenant_id=f"other-{uuid4()}",
            task_id=first.task_id,
        )


@pytest.mark.asyncio
async def test_unleased_cancellation_cannot_revoke_worker_lease(workflow_database) -> None:
    pool, _admin = workflow_database
    store = PostgresWorkflowStore(pool)
    tenant = f"tenant-{uuid4()}"
    task = await store.create_task(
        **new_task_args(tenant_id=tenant, suffix=str(uuid4()))
    )
    claimed = await store.claim_next(
        tenant_id=tenant,
        worker_id="worker-cancel-race",
        supported_task_types=("integration_work",),
        lease_seconds=30,
    )
    assert claimed is not None

    with pytest.raises(LeaseLost):
        await store.transition(
            task_id=task.task_id,
            tenant_id=tenant,
            expected_version=claimed.version,
            target=TaskState.CANCELLED,
            actor_id=claimed.actor_id,
            reason_code="user_cancelled",
            require_lease=False,
            require_no_lease=True,
        )

@pytest.mark.asyncio
async def test_task_results_are_encrypted_immutable_idempotent_and_tenant_scoped(workflow_database) -> None:
    pool, admin = workflow_database
    store = PostgresWorkflowStore(pool)
    tenant = f"tenant-{uuid4()}"
    actor = "notebook-result-owner"
    task = await store.create_task(
        **new_task_args(tenant_id=tenant, actor_id=actor, suffix=str(uuid4()))
    )
    result = {
        "task_id": str(task.task_id),
        "candidate_answer": "private reasoning output",
        "verification_status": "needs_human_review",
    }
    cipher = TaskPayloadCipher(b"r" * 32, key_version="result-v1")
    envelope = cipher.encrypt_json(result, tenant_id=tenant, task_id=task.task_id)
    digest = hashlib.sha256(
        json.dumps(
            result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    ).hexdigest()

    first = await store.save_task_result(
        task_id=task.task_id,
        tenant_id=tenant,
        actor_id=actor,
        encrypted_payload=envelope.ciphertext,
        payload_nonce=envelope.nonce,
        payload_key_version=envelope.key_version,
        result_digest=digest,
    )
    repeated = await store.save_task_result(
        task_id=task.task_id,
        tenant_id=tenant,
        actor_id=actor,
        encrypted_payload=envelope.ciphertext,
        payload_nonce=envelope.nonce,
        payload_key_version=envelope.key_version,
        result_digest=digest,
    )
    assert repeated.result_digest == first.result_digest
    assert b"private reasoning output" not in first.ciphertext

    loaded = await store.get_task_result(
        task_id=task.task_id, tenant_id=tenant, actor_id=actor
    )
    recovered = cipher.decrypt_json(
        EncryptedTaskPayload(
            ciphertext=loaded.ciphertext,
            nonce=loaded.nonce,
            key_version=loaded.key_version,
        ),
        tenant_id=tenant,
        task_id=task.task_id,
    )
    assert recovered == result

    with pytest.raises(TaskNotFound):
        await store.get_task_result(
            task_id=task.task_id, tenant_id=f"other-{uuid4()}"
        )
    with pytest.raises(TaskNotFound):
        await store.get_task_result(
            task_id=task.task_id, tenant_id=tenant, actor_id="other-actor"
        )
    with pytest.raises(IdempotencyConflict):
        await store.save_task_result(
            task_id=task.task_id,
            tenant_id=tenant,
            actor_id=actor,
            encrypted_payload=envelope.ciphertext,
            payload_nonce=envelope.nonce,
            payload_key_version=envelope.key_version,
            result_digest="f" * 64,
        )

    role_result = await admin.fetchval(
        """
        SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user
        """
    )
    assert role_result is True  # administrative test connection only


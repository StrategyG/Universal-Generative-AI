"""Dedicated supervised process for the reasoning-only Notebook task queue.

Run as a separate deployment with WORKFLOW_WORKER_DATABASE_URL mapped to a
login that is a member of ugai_workflow_worker, never the API database login.
"""
from __future__ import annotations

import asyncio
import json
import logging
import signal

from app.config import (
    settings,
    validate_database_configuration,
    validate_workflow_task_configuration,
    validate_workflow_worker_configuration,
)
from app.notebook_task_worker import (
    NotebookReasoningTaskHandler,
    reconcile_outcome_unknown_once,
)
from app.observability import configure_logging
from app.services.external_gpu_queue import close_queue, initialize_queue
from ugai_workflow.payload_cipher import TaskPayloadCipher
from ugai_workflow.postgres_store import PostgresWorkflowStore
from ugai_workflow.worker import HybridWorker, WorkerRegistration, WorkerTier

logger = logging.getLogger("ugai.notebook_worker")
_NOTEBOOK_TASK_TYPE = "notebook_task"


async def _assert_worker_database_role(pool: object) -> None:
    """Prove the worker uses a distinct least-privilege login and not the API role."""
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            """
            SELECT
                role.rolsuper AS is_superuser,
                role.rolbypassrls AS bypasses_rls,
                pg_has_role(current_user, 'ugai_workflow_worker', 'member')
                    AS worker_role_member,
                pg_has_role(current_user, 'ugai_workflow_runtime', 'member')
                    AS api_runtime_role_member,
                NOT pg_has_role(current_user, namespace.nspowner, 'member')
                    AS not_schema_owner,
                NOT EXISTS (
                    SELECT 1
                    FROM pg_class relation
                    JOIN pg_namespace relation_namespace
                      ON relation_namespace.oid = relation.relnamespace
                    WHERE relation_namespace.nspname = 'ugai_workflow'
                      AND relation.relname IN (
                        'tasks', 'events', 'task_payloads', 'task_results', 'workers'
                      )
                      AND pg_has_role(current_user, relation.relowner, 'member')
                ) AS not_table_owner,
                has_table_privilege(current_user, 'ugai_workflow.tasks', 'SELECT')
                    AS tasks_select,
                has_table_privilege(current_user, 'ugai_workflow.tasks', 'UPDATE')
                    AS tasks_update,
                has_table_privilege(current_user, 'ugai_workflow.events', 'INSERT')
                    AS events_insert,
                has_table_privilege(current_user, 'ugai_workflow.task_payloads', 'SELECT')
                    AS payloads_select,
                has_table_privilege(current_user, 'ugai_workflow.task_results', 'INSERT')
                    AS results_insert,
                has_table_privilege(current_user, 'ugai_workflow.workers', 'UPDATE')
                    AS workers_update
            FROM pg_roles role
            CROSS JOIN pg_namespace namespace
            WHERE role.rolname = current_user
              AND namespace.nspname = 'ugai_workflow'
            """
        )
    required = (
        "worker_role_member",
        "not_schema_owner",
        "not_table_owner",
        "tasks_select",
        "tasks_update",
        "events_insert",
        "payloads_select",
        "results_insert",
        "workers_update",
    )
    if (
        row is None
        or row["is_superuser"]
        or row["bypasses_rls"]
        or row["api_runtime_role_member"]
        or any(not row[field] for field in required)
    ):
        raise RuntimeError(
            "Worker database login must be distinct, non-owner, NOBYPASSRLS, "
            "and a member only of ugai_workflow_worker"
        )


async def run_worker() -> None:
    if not settings.workflow_worker_enabled:
        raise RuntimeError("WORKFLOW_WORKER_ENABLED=true is required")
    validate_database_configuration()
    validate_workflow_task_configuration()
    validate_workflow_worker_configuration()

    import asyncpg

    previous_keys = json.loads(settings.workflow_payload_previous_keys_json or "{}")
    cipher = TaskPayloadCipher(
        settings.workflow_payload_encryption_key,
        key_id=settings.workflow_payload_key_id,
        previous_keys=previous_keys,
    )
    pool = await asyncpg.create_pool(
        dsn=settings.workflow_worker_database_url,
        min_size=1,
        max_size=8,
        command_timeout=15,
        server_settings={"application_name": "ugai-notebook-worker"},
    )
    store = PostgresWorkflowStore(pool)
    worker_id = settings.workflow_worker_id.strip()
    tenant_id = settings.workflow_worker_tenant_id.strip()
    stop = asyncio.Event()
    heartbeat_task: asyncio.Task | None = None
    registered = False
    queue_initialized = False

    try:
        await _assert_worker_database_role(pool)
        # The reasoning route catalog is approved against the canonical model
        # registry initialized by the same queue bootstrap used by the API.
        await initialize_queue()
        queue_initialized = True
        registration = WorkerRegistration(
            worker_id=worker_id,
            tier=WorkerTier.DEDICATED,
            tenant_id=tenant_id,
            task_types=(_NOTEBOOK_TASK_TYPE,),
            lease_seconds=settings.workflow_worker_lease_seconds,
            heartbeat_seconds=settings.workflow_worker_heartbeat_seconds,
        )
        registration.validate()
        worker = HybridWorker(
            store=store,
            registration=registration,
            handlers={
                _NOTEBOOK_TASK_TYPE: NotebookReasoningTaskHandler(
                    store=store,
                    cipher=cipher,
                )
            },
        )
        loop = asyncio.get_running_loop()
        for name in ("SIGINT", "SIGTERM"):
            value = getattr(signal, name, None)
            if value is not None:
                try:
                    loop.add_signal_handler(value, stop.set)
                except (NotImplementedError, RuntimeError):
                    logger.warning("worker_signal_handler_unavailable", extra={"signal": name})

        await store.heartbeat_worker(
            tenant_id=tenant_id,
            worker_id=worker_id,
            task_types=(_NOTEBOOK_TASK_TYPE,),
        )
        registered = True

        async def heartbeat_loop() -> None:
            while not stop.is_set():
                try:
                    await asyncio.wait_for(
                        stop.wait(),
                        timeout=settings.workflow_worker_heartbeat_seconds,
                    )
                    return
                except TimeoutError:
                    pass
                try:
                    await store.heartbeat_worker(
                        tenant_id=tenant_id,
                        worker_id=worker_id,
                        task_types=(_NOTEBOOK_TASK_TYPE,),
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("worker_registry_heartbeat_failed")
                    stop.set()
                    return

        heartbeat_task = asyncio.create_task(heartbeat_loop())
        logger.info(
            "notebook_reasoning_worker_started",
            extra={
                "worker_id": worker_id,
                "tenant_id": tenant_id,
                "task_type": _NOTEBOOK_TASK_TYPE,
                "poll_seconds": settings.workflow_worker_poll_seconds,
            },
        )

        while not stop.is_set():
            try:
                await reconcile_outcome_unknown_once(
                    store=store,
                    cipher=cipher,
                    tenant_id=tenant_id,
                    limit=50,
                )
                worked = await worker.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("notebook_worker_iteration_failed")
                worked = False
            if not worked:
                try:
                    await asyncio.wait_for(
                        stop.wait(),
                        timeout=settings.workflow_worker_poll_seconds,
                    )
                except TimeoutError:
                    continue
    finally:
        stop.set()
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
        if registered:
            try:
                await store.deregister_worker(tenant_id=tenant_id, worker_id=worker_id)
            except Exception:
                logger.exception("worker_registry_deregister_failed")
        await pool.close()
        if queue_initialized:
            await close_queue()
        logger.info("notebook_reasoning_worker_stopped", extra={"worker_id": worker_id})


def main() -> None:
    configure_logging()
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()

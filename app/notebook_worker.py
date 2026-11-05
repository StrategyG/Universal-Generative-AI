"""Dedicated, tenant-scoped UGAI Notebook reasoning worker.

Run as a separate process:
    python -m app.notebook_worker

The process handles only the configured tenant and the explicitly allowed
notebook_request task type. API task acceptance is gated by its PostgreSQL
worker heartbeat; a crashed worker naturally ages out of the registry.
"""
from __future__ import annotations

import asyncio
import logging
import signal

from app.config import settings
from app.notebook_task_worker import (
    NotebookReasoningTaskHandler,
    reconcile_outcome_unknown_once,
)
from app.observability import configure_logging
from app.workflow_runtime import open_workflow_runtime
from ugai_workflow.worker import HybridWorker, WorkerRegistration, WorkerTier

logger = logging.getLogger("ugai.notebook_worker")
_NOTEBOOK_TASK_TYPE = "notebook_request"
_REGISTRY_HEARTBEAT_SECONDS = 15


async def _heartbeat_registry(runtime, *, tenant_id: str, worker_id: str, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            active = await runtime.store.heartbeat_worker(
                tenant_id=tenant_id,
                worker_id=worker_id,
            )
            if not active:
                await runtime.store.register_worker(
                    tenant_id=tenant_id,
                    worker_id=worker_id,
                    task_types=(_NOTEBOOK_TASK_TYPE,),
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            # A stale heartbeat closes API intake after the API's 60-second
            # freshness window; this process does not fake its availability.
            logger.exception("worker_registry_heartbeat_failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=_REGISTRY_HEARTBEAT_SECONDS)
        except TimeoutError:
            continue


async def run_worker() -> None:
    if not settings.workflow_worker_enabled:
        raise RuntimeError("UGAI_WORKFLOW_WORKER_ENABLED must be true")
    tenant_id = settings.workflow_worker_tenant_id.strip()
    worker_id = settings.workflow_worker_id.strip()
    if not tenant_id:
        raise RuntimeError("UGAI_WORKFLOW_WORKER_TENANT_ID is required")
    if not worker_id:
        raise RuntimeError("UGAI_WORKFLOW_WORKER_ID is required")

    runtime = await open_workflow_runtime(settings)
    if runtime is None:
        raise RuntimeError("Durable workflow runtime did not initialize")
    heartbeat_task: asyncio.Task | None = None
    registered = False
    stop = asyncio.Event()
    try:
        if _NOTEBOOK_TASK_TYPE not in runtime.enabled_task_types:
            raise RuntimeError(
                "UGAI_WORKFLOW_ENABLED_TASK_TYPES must explicitly include notebook_request"
            )

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
            store=runtime.store,
            registration=registration,
            handlers={
                _NOTEBOOK_TASK_TYPE: NotebookReasoningTaskHandler(runtime=runtime),
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

        await runtime.store.register_worker(
            tenant_id=tenant_id,
            worker_id=worker_id,
            task_types=(_NOTEBOOK_TASK_TYPE,),
        )
        registered = True
        heartbeat_task = asyncio.create_task(
            _heartbeat_registry(runtime, tenant_id=tenant_id, worker_id=worker_id, stop=stop)
        )
        logger.info(
            "notebook_worker_started",
            extra={
                "worker_id": worker_id,
                "tenant_id": tenant_id,
                "task_types": [_NOTEBOOK_TASK_TYPE],
                "lease_seconds": registration.lease_seconds,
            },
        )
        while not stop.is_set():
            try:
                await reconcile_outcome_unknown_once(
                    runtime,
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
                    pass
    finally:
        stop.set()
        if heartbeat_task is not None:
            await heartbeat_task
        try:
            if registered:
                await runtime.store.deregister_worker(
                    tenant_id=tenant_id,
                    worker_id=worker_id,
                )
        finally:
            await runtime.close()
        logger.info("notebook_worker_stopped", extra={"worker_id": worker_id})


def main() -> None:
    configure_logging()
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()

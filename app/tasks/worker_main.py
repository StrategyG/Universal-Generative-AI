"""Dedicated process entry point for tenant-scoped Notebook reasoning tasks.

Run as a separate service:
    python -m app.tasks.worker_main

Set WORKFLOW_WORKER_TENANT_ID from the deployment's trusted tenant binding.
Do not expose this worker's database connection or payload key to model providers.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from app.config import settings
from app.observability import configure_logging
from app.tasks.notebook_handler import NotebookReasoningTaskHandler
from app.tasks.runtime import open_task_runtime
from ugai_workflow import (
    HybridWorker,
    WorkerRegistration,
    WorkerTier,
)


logger = logging.getLogger("ugai.notebook_worker")


async def run_worker() -> None:
    if not settings.workflow_tasks_enabled:
        raise RuntimeError("WORKFLOW_TASKS_ENABLED must be true for the worker process")
    tenant_id = settings.workflow_worker_tenant_id.strip()
    if not tenant_id:
        raise RuntimeError("WORKFLOW_WORKER_TENANT_ID is required")
    if not settings.workflow_worker_id.strip():
        raise RuntimeError("WORKFLOW_WORKER_ID is required")
    if not 0.1 <= settings.workflow_worker_poll_seconds <= 30:
        raise RuntimeError("WORKFLOW_WORKER_POLL_SECONDS must be between 0.1 and 30")

    runtime = await open_task_runtime(settings)
    if runtime is None:
        raise RuntimeError("Durable task runtime did not initialize")
    try:
        registration = WorkerRegistration(
            worker_id=settings.workflow_worker_id,
            tier=WorkerTier.DEDICATED,
            tenant_id=tenant_id,
            task_types=("notebook.request",),
            lease_seconds=settings.workflow_worker_lease_seconds,
            heartbeat_seconds=settings.workflow_worker_heartbeat_seconds,
        )
        worker = HybridWorker(
            store=runtime.service.store,
            registration=registration,
            handlers={
                "notebook.request": NotebookReasoningTaskHandler(
                    task_service=runtime.service
                )
            },
        )

        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signal_name in ("SIGINT", "SIGTERM"):
            signal_value = getattr(signal, signal_name, None)
            if signal_value is not None:
                try:
                    loop.add_signal_handler(signal_value, stop_event.set)
                except (NotImplementedError, RuntimeError):
                    logger.warning("signal_handler_unavailable", extra={"signal": signal_name})

        logger.info(
            "notebook_worker_started",
            extra={
                "worker_id": registration.worker_id,
                "tenant_id": registration.tenant_id,
                "tier": registration.tier.value,
                "task_types": list(registration.task_types),
            },
        )
        while not stop_event.is_set():
            try:
                worked = await worker.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Errors are visible to process monitoring. A task with an
                # uncertain external outcome is reconciled by its durable state.
                logger.exception("notebook_worker_iteration_failed")
                worked = False
            if not worked:
                try:
                    await asyncio.wait_for(
                        stop_event.wait(),
                        timeout=settings.workflow_worker_poll_seconds,
                    )
                except TimeoutError:
                    pass
        logger.info("notebook_worker_stopping", extra={"worker_id": registration.worker_id})
    finally:
        await runtime.close()


def main() -> None:
    configure_logging()
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()

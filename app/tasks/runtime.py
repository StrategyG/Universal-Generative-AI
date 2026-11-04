"""Lifecycle for the separately credentialed durable workflow task database."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.tasks.payloads import TaskPayloadCipher
from app.tasks.service import UGAITaskService
from ugai_workflow.postgres_store import PostgresWorkflowStore


@dataclass(slots=True)
class TaskRuntime:
    pool: Any
    service: UGAITaskService

    async def close(self) -> None:
        await self.pool.close()


async def open_task_runtime(settings: Settings) -> TaskRuntime | None:
    if not settings.workflow_tasks_enabled:
        return None
    if not settings.workflow_database_url.strip():
        raise RuntimeError("WORKFLOW_DATABASE_URL is required when workflow tasks are enabled")
    cipher = TaskPayloadCipher.from_base64(
        settings.task_payload_encryption_key,
        key_version=settings.task_payload_key_version,
    )
    if settings.environment.lower() in {"production", "prod"}:
        ssl_mode = settings.workflow_database_ssl_mode
        if ssl_mode != "verify-full":
            raise RuntimeError("Production workflow database SSL mode must be verify-full")
    else:
        ssl_mode = settings.workflow_database_ssl_mode
    try:
        import asyncpg
    except ImportError as exc:
        raise RuntimeError("Install the UGAI postgres extra to enable workflow tasks") from exc
    pool = await asyncpg.create_pool(
        dsn=settings.workflow_database_url,
        min_size=1,
        max_size=10,
        command_timeout=15,
        ssl=ssl_mode,
    )
    try:
        store = PostgresWorkflowStore(pool)
        service = UGAITaskService(store, cipher)
        return TaskRuntime(pool=pool, service=service)
    except Exception:
        await pool.close()
        raise

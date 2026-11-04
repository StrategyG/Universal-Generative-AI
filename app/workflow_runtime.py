"""Composition root for the durable UGAI task API runtime."""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from app.config import Settings, settings
from ugai_workflow.input_vault import WorkflowInputVault
from ugai_workflow.postgres_store import PostgresWorkflowStore


@dataclass(slots=True)
class WorkflowRuntime:
    pool: object
    store: PostgresWorkflowStore
    inputs: WorkflowInputVault
    task_acceptance_enabled: bool
    enabled_task_types: frozenset[str]

    async def close(self) -> None:
        close = getattr(self.pool, "close", None)
        if callable(close):
            await close()


def _decode_keyring(config: Settings) -> dict[str, bytes]:
    try:
        raw = json.loads(config.workflow_input_keyring_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("UGAI_WORKFLOW_INPUT_KEYRING_JSON must be a JSON object") from exc
    if not isinstance(raw, dict) or not raw:
        raise RuntimeError("UGAI workflow input encryption keyring is not configured")
    result: dict[str, bytes] = {}
    for key_id, encoded in raw.items():
        if not isinstance(key_id, str) or not isinstance(encoded, str) or not encoded:
            raise RuntimeError("UGAI workflow input keyring entry is invalid")
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise RuntimeError("UGAI workflow input keyring contains invalid base64") from exc
        if len(decoded) != 32:
            raise RuntimeError("UGAI workflow input keys must decode to exactly 32 bytes")
        result[key_id] = decoded
    if config.workflow_input_active_key_id not in result:
        raise RuntimeError("UGAI_WORKFLOW_INPUT_ACTIVE_KEY_ID is not present in the keyring")
    return result


def _validate_workflow_database_url(config: Settings) -> None:
    raw = config.workflow_database_url.strip()
    if not raw:
        raise RuntimeError("UGAI_WORKFLOW_DATABASE_URL is required when workflow runtime is enabled")
    try:
        parsed = urlsplit(raw)
        query = parse_qs(parsed.query, keep_blank_values=True)
    except ValueError as exc:
        raise RuntimeError("UGAI_WORKFLOW_DATABASE_URL is invalid") from exc
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        raise RuntimeError("UGAI_WORKFLOW_DATABASE_URL must be a PostgreSQL DSN")
    if config.environment.strip().lower() in {"production", "prod"}:
        modes = query.get("sslmode", [])
        if len(modes) != 1 or modes[0].strip().lower() != "verify-full":
            raise RuntimeError(
                "Production UGAI_WORKFLOW_DATABASE_URL must use exactly one sslmode=verify-full"
            )


def _enabled_task_types(config: Settings) -> frozenset[str]:
    values = [item.strip() for item in config.workflow_enabled_task_types.split(",") if item.strip()]
    if any(len(item) > 128 for item in values) or len(set(values)) != len(values):
        raise RuntimeError("UGAI_WORKFLOW_ENABLED_TASK_TYPES contains invalid or duplicate values")
    return frozenset(values)


async def open_workflow_runtime(config: Settings = settings) -> WorkflowRuntime | None:
    """Open a separate non-owner runtime pool; no volatile production fallback exists."""
    enabled_types = _enabled_task_types(config)
    if not config.workflow_database_url.strip():
        if config.workflow_task_acceptance_enabled:
            raise RuntimeError("Workflow task acceptance requires UGAI_WORKFLOW_DATABASE_URL")
        return None

    _validate_workflow_database_url(config)
    keyring = _decode_keyring(config)
    if config.workflow_task_acceptance_enabled and not enabled_types:
        raise RuntimeError(
            "Workflow task acceptance cannot be enabled without an explicit task-type allowlist"
        )

    try:
        import asyncpg
    except ImportError as exc:
        raise RuntimeError("Install the UGAI postgres extra for workflow persistence") from exc

    pool = await asyncpg.create_pool(
        dsn=config.workflow_database_url,
        min_size=2,
        max_size=10,
        command_timeout=10,
        max_inactive_connection_lifetime=300,
    )
    try:
        store = PostgresWorkflowStore(pool)
        inputs = WorkflowInputVault(
            pool=pool,
            active_key_id=config.workflow_input_active_key_id,
            keyring=keyring,
        )
        return WorkflowRuntime(
            pool=pool,
            store=store,
            inputs=inputs,
            task_acceptance_enabled=config.workflow_task_acceptance_enabled,
            enabled_task_types=enabled_types,
        )
    except Exception:
        await pool.close()
        raise

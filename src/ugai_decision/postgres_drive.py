"""PostgreSQL audit and Google Drive evidence adapters."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from .workflow import DecisionAuditEvent


class AsyncPostgresPool(Protocol):
    def acquire(self) -> Any: ...


@dataclass(frozen=True, slots=True)
class DriveEvidenceReceipt:
    file_id: str
    name: str
    mime_type: str
    sha256: str
    size_bytes: int
    web_view_link: str | None


class GoogleDriveEvidenceArchive:
    """Archive evidence in a restricted Drive folder using an injected Drive v3 client."""

    def __init__(self, *, drive_service: Any, folder_id: str) -> None:
        if not isinstance(folder_id, str) or not folder_id.strip():
            raise ValueError("a non-empty Google Drive folder_id is required")
        self._service = drive_service
        self._folder_id = folder_id

    async def archive(
        self, *, content: bytes, filename: str, mime_type: str = "application/octet-stream"
    ) -> DriveEvidenceReceipt:
        if not isinstance(content, bytes) or not content:
            raise ValueError("evidence content must be non-empty bytes")
        if (not filename or len(filename) > 255 or "/" in filename or "\\" in filename):
            raise ValueError("filename must be a safe basename")
        if not re.fullmatch(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+", mime_type):
            raise ValueError("mime_type must be a valid type/subtype")
        digest = hashlib.sha256(content).hexdigest()

        def upload() -> Mapping[str, Any]:
            from googleapiclient.http import MediaInMemoryUpload
            media = MediaInMemoryUpload(content, mimetype=mime_type, resumable=False)
            return self._service.files().create(
                body={
                    "name": filename,
                    "mimeType": mime_type,
                    "parents": [self._folder_id],
                    "appProperties": {"sha256": digest},
                },
                media_body=media,
                fields="id,name,mimeType,webViewLink",
            ).execute()

        result = await asyncio.to_thread(upload)
        file_id = result.get("id")
        if not isinstance(file_id, str) or not file_id:
            raise RuntimeError("Google Drive upload returned no file id")
        return DriveEvidenceReceipt(
            file_id=file_id,
            name=str(result.get("name") or filename),
            mime_type=str(result.get("mimeType") or mime_type),
            sha256=digest,
            size_bytes=len(content),
            web_view_link=result.get("webViewLink"),
        )


class PostgresDecisionAuditSink:
    """Append-only audit sink backed by an asyncpg-compatible pool."""

    def __init__(self, *, pool: AsyncPostgresPool) -> None:
        self._pool = pool

    async def append(self, event: DecisionAuditEvent) -> None:
        if not isinstance(event, DecisionAuditEvent):
            raise TypeError("event must be a DecisionAuditEvent")
        try:
            occurred_at = datetime.fromisoformat(event.occurred_at)
        except (TypeError, ValueError) as exc:
            raise ValueError("occurred_at must be ISO-8601") from exc
        if occurred_at.tzinfo is None:
            raise ValueError("occurred_at must include a timezone")
        details = dict(event.details)
        if len(details) > 64 or any(len(k) > 128 or len(v) > 2048 for k, v in details.items()):
            raise ValueError("audit details exceed metadata limits")
        payload = json.dumps(details, sort_keys=True, separators=(",", ":"), allow_nan=False)
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO ugai_audit.decision_events
                    (event_id, workflow_id, decision_id, actor_id, stage, outcome,
                     occurred_at, details)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
                ON CONFLICT (event_id) DO NOTHING
                """,
                event.event_id, event.workflow_id, event.decision_id, event.actor_id,
                event.stage, event.outcome, occurred_at.astimezone(UTC), payload,
            )


class PostgresEvidenceRegistry:
    """Store Drive object identity and integrity metadata in PostgreSQL."""

    def __init__(self, *, pool: AsyncPostgresPool) -> None:
        self._pool = pool

    async def register(
        self, *, evidence_id: str, actor_id: str, receipt: DriveEvidenceReceipt,
        source_uri: str | None = None,
    ) -> None:
        if not evidence_id or not actor_id:
            raise ValueError("evidence_id and actor_id are required")
        if not re.fullmatch(r"[a-f0-9]{64}", receipt.sha256):
            raise ValueError("receipt SHA-256 is invalid")
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO ugai_audit.evidence_objects
                    (evidence_id, actor_id, drive_file_id, file_name, mime_type,
                     sha256, size_bytes, web_view_link, source_uri)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (evidence_id) DO NOTHING
                """,
                evidence_id, actor_id, receipt.file_id, receipt.name, receipt.mime_type,
                receipt.sha256, receipt.size_bytes, receipt.web_view_link, source_uri,
            )

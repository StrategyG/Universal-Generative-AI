"""Framework-neutral contracts for replayable outbox replication."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Mapping, Protocol, Sequence
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ReplicationEvent:
    event_id: UUID
    stream_name: str
    stream_sequence: int
    aggregate_key: str
    event_type: str
    schema_version: int
    source_position: str
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        for field_name in ("stream_name", "aggregate_key", "event_type", "source_position"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.stream_sequence < 1 or self.schema_version < 1:
            raise ValueError("stream_sequence and schema_version must be positive")
        try:
            json.dumps(self.payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("payload must be finite JSON data") from exc

    @property
    def payload_sha256(self) -> str:
        canonical = json.dumps(
            self.payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
        return sha256(canonical).hexdigest()


@dataclass(frozen=True, slots=True)
class SyncBatchResult:
    stream_name: str
    received: int
    applied: int
    duplicates: int
    checkpoint: int | None


class SourceOutbox(Protocol):
    def read_after(self, stream_name: str, checkpoint: int | None, limit: int) -> Sequence[ReplicationEvent]: ...


class TargetStore(Protocol):
    def apply_batch_atomically(
        self, stream_name: str, events: Sequence[ReplicationEvent], expected_checkpoint: int | None
    ) -> tuple[int, int, int | None]:
        """Commit entity rows, event receipts and checkpoint in one DB transaction.

        Return (applied, duplicates, new_checkpoint). Reject stale/fenced workers
        and unsupported schema versions. source_position is retained for audit,
        but ordering uses the monotonic per-stream sequence, not lexical WAL text.
        """
        ...


class ReplicationWorker:
    """Deterministic worker; transport, leases and SQL live in adapters."""

    def __init__(self, source: SourceOutbox, target: TargetStore, *, batch_size: int = 250) -> None:
        if batch_size < 1 or batch_size > 10_000:
            raise ValueError("batch_size must be between 1 and 10000")
        self._source = source
        self._target = target
        self._batch_size = batch_size

    def run_once(self, stream_name: str, checkpoint: int | None) -> SyncBatchResult:
        if not stream_name.strip():
            raise ValueError("stream_name must not be empty")
        events = tuple(self._source.read_after(stream_name, checkpoint, self._batch_size))
        if len(events) > self._batch_size:
            raise ValueError("source returned more events than requested")
        previous_sequence = checkpoint
        seen_ids: set[UUID] = set()
        for event in events:
            if event.stream_name != stream_name:
                raise ValueError("source returned an event from another stream")
            if event.event_id in seen_ids:
                raise ValueError("source returned duplicate event IDs in one batch")
            seen_ids.add(event.event_id)
            if previous_sequence is not None and event.stream_sequence <= previous_sequence:
                raise ValueError("events must be strictly ordered after the checkpoint")
            previous_sequence = event.stream_sequence
        applied, duplicates, new_checkpoint = self._target.apply_batch_atomically(
            stream_name, events, checkpoint
        )
        if applied < 0 or duplicates < 0 or applied + duplicates != len(events):
            raise RuntimeError("target returned inconsistent batch accounting")
        if events and new_checkpoint != events[-1].stream_sequence:
            raise RuntimeError("target checkpoint does not match the final committed event")
        if not events and new_checkpoint != checkpoint:
            raise RuntimeError("empty batch must not advance the checkpoint")
        return SyncBatchResult(stream_name, len(events), applied, duplicates, new_checkpoint)

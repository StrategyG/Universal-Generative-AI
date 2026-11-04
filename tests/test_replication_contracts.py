from uuid import uuid4

import pytest

from ugai_replication.contracts import ReplicationEvent, ReplicationWorker


class Source:
    def __init__(self, events):
        self.events = events

    def read_after(self, stream_name, checkpoint, limit):
        return self.events[:limit]


class Target:
    def __init__(self, applied=None):
        self.applied = applied or []

    def apply_batch_atomically(self, stream_name, events, expected_checkpoint):
        fresh = [event for event in events if event.event_id not in self.applied]
        self.applied.extend(event.event_id for event in fresh)
        checkpoint = events[-1].source_position if events else expected_checkpoint
        return len(fresh), len(events) - len(fresh), checkpoint


def event(position="0001", *, stream="rag.documents", payload=None):
    return ReplicationEvent(
        event_id=uuid4(), stream_name=stream, aggregate_key="doc-1",
        event_type="document.upserted", schema_version=1,
        source_position=position, payload=payload or {"id": "doc-1", "title": "A"},
    )


def test_applies_batch_and_advances_checkpoint():
    events = [event("0001"), event("0002")]
    target = Target()
    result = ReplicationWorker(Source(events), target).run_once("rag.documents", None)
    assert (result.received, result.applied, result.duplicates) == (2, 2, 0)
    assert result.checkpoint == "0002"


def test_rejects_cross_stream_event_before_target_write():
    target = Target()
    worker = ReplicationWorker(Source([event(stream="rag.chunks")]), target)
    with pytest.raises(ValueError, match="another stream"):
        worker.run_once("rag.documents", None)
    assert target.applied == []


def test_rejects_non_monotonic_source_positions():
    target = Target()
    worker = ReplicationWorker(Source([event("0002"), event("0001")]), target)
    with pytest.raises(ValueError, match="strictly ordered"):
        worker.run_once("rag.documents", None)
    assert target.applied == []


def test_rejects_duplicate_event_ids_in_batch():
    item = event()
    target = Target()
    worker = ReplicationWorker(Source([item, item]), target)
    with pytest.raises(ValueError, match="duplicate event IDs"):
        worker.run_once("rag.documents", None)


def test_payload_digest_is_stable_across_key_order():
    a = event(payload={"a": 1, "b": 2})
    b = ReplicationEvent(
        event_id=uuid4(), stream_name=a.stream_name, aggregate_key=a.aggregate_key,
        event_type=a.event_type, schema_version=a.schema_version,
        source_position="0002", payload={"b": 2, "a": 1},
    )
    assert a.payload_sha256 == b.payload_sha256


def test_rejects_non_json_payload():
    with pytest.raises(ValueError, match="finite JSON"):
        event(payload={"bad": object()})


def test_empty_batch_does_not_move_checkpoint():
    result = ReplicationWorker(Source([]), Target()).run_once("rag.documents", "0007")
    assert result.received == 0
    assert result.checkpoint == "0007"

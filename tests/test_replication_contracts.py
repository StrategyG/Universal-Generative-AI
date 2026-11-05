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
        fresh = [item for item in events if item.event_id not in self.applied]
        self.applied.extend(item.event_id for item in fresh)
        checkpoint = events[-1].stream_sequence if events else expected_checkpoint
        return len(fresh), len(events) - len(fresh), checkpoint


def event(sequence=1, *, source_position="0/1", stream="rag.documents", payload=None):
    return ReplicationEvent(
        event_id=uuid4(), stream_name=stream, stream_sequence=sequence,
        aggregate_key="doc-1", event_type="document.upserted", schema_version=1,
        source_position=source_position, payload=payload or {"id": "doc-1", "title": "A"},
    )


def test_applies_batch_and_advances_checkpoint():
    events = [event(1), event(2, source_position="0/10")]
    target = Target()
    result = ReplicationWorker(Source(events), target).run_once("rag.documents", None)
    assert (result.received, result.applied, result.duplicates) == (2, 2, 0)
    assert result.checkpoint == 2


def test_rejects_cross_stream_event_before_target_write():
    target = Target()
    worker = ReplicationWorker(Source([event(stream="rag.chunks")]), target)
    with pytest.raises(ValueError, match="another stream"):
        worker.run_once("rag.documents", None)
    assert target.applied == []


def test_rejects_non_monotonic_sequence():
    target = Target()
    worker = ReplicationWorker(Source([event(2), event(1)]), target)
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
    b = event(2, payload={"b": 2, "a": 1})
    assert a.payload_sha256 == b.payload_sha256


def test_rejects_non_json_payload():
    with pytest.raises(ValueError, match="finite JSON"):
        event(payload={"bad": object()})


def test_empty_batch_does_not_move_checkpoint():
    result = ReplicationWorker(Source([]), Target()).run_once("rag.documents", 7)
    assert result.received == 0
    assert result.checkpoint == 7

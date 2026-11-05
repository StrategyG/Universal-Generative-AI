import pytest

from ugai_workflow.postgres_store import (
    PostgresWorkflowStore,
    _safe_event_details,
    _safe_metadata,
    canonical_json_digest,
    retry_backoff_seconds,
)


class FakePoolWithoutAcquire:
    pass


def test_store_requires_async_pool() -> None:
    with pytest.raises(ValueError, match="async_postgres_pool_required"):
        PostgresWorkflowStore(FakePoolWithoutAcquire())


def test_canonical_digest_is_order_independent() -> None:
    assert canonical_json_digest({"a": 1, "b": 2}) == canonical_json_digest({"b": 2, "a": 1})


@pytest.mark.parametrize("value", [{"bad": float("nan")}, {"bad": object()}])
def test_canonical_digest_rejects_non_json_values(value) -> None:
    with pytest.raises(ValueError, match="finite_json"):
        canonical_json_digest(value)


def test_canonical_digest_rejects_large_input() -> None:
    with pytest.raises(ValueError, match="too_large"):
        canonical_json_digest({"blob": "x" * (65 * 1024)})


def test_task_metadata_is_allowlisted_and_bounded() -> None:
    assert _safe_metadata({"request_ref": "req-001"}) == {"request_ref": "req-001"}
    with pytest.raises(ValueError, match="not_allowlisted"):
        _safe_metadata({"prompt": "do not store raw prompts"})


def test_event_metadata_rejects_secrets_and_free_text() -> None:
    assert _safe_event_details({"attempt": 2, "verification_status": "passed"}) == {
        "attempt": 2,
        "verification_status": "passed",
    }
    with pytest.raises(ValueError, match="not_allowlisted"):
        _safe_event_details({"access_token": "never-store"})



@pytest.mark.parametrize(
    ("attempt", "expected"),
    [(0, 30), (1, 60), (2, 120), (3, 240), (7, 3600), (16, 3600), (32, 3600)],
)
def test_retry_backoff_is_exponential_and_capped(attempt, expected) -> None:
    assert retry_backoff_seconds(attempt) == expected


@pytest.mark.parametrize("attempt", [-1, True, 1.5, "1"])
def test_retry_backoff_rejects_invalid_attempt(attempt) -> None:
    with pytest.raises(ValueError, match="retry_attempt_invalid"):
        retry_backoff_seconds(attempt)


def test_retry_backoff_rejects_unsafe_bounds() -> None:
    with pytest.raises(ValueError, match="retry_base_delay_out_of_bounds"):
        retry_backoff_seconds(0, base_delay_seconds=0)
    with pytest.raises(ValueError, match="retry_max_delay_out_of_bounds"):
        retry_backoff_seconds(0, base_delay_seconds=30, max_delay_seconds=29)

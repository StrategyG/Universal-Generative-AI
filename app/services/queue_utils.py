import hashlib
import json

from app.workers.schemas import ExternalJobCreate


def request_fingerprint(request: ExternalJobCreate) -> str:
    payload = request.model_dump(mode="json", exclude={"idempotency_key"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()



RETRY_BASE_SECONDS = 5
RETRY_MAX_SECONDS = 300


def retry_delay_seconds(attempts: int) -> int:
    """Return capped exponential backoff after a failed execution attempt."""
    exponent = max(attempts - 1, 0)
    return min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * (2**exponent))

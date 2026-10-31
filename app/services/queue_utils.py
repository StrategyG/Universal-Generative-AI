import hashlib
import json

from app.workers.schemas import ExternalJobCreate


def request_fingerprint(request: ExternalJobCreate) -> str:
    payload = request.model_dump(mode="json", exclude={"idempotency_key"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

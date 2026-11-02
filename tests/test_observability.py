import json
import logging
import re

from fastapi.testclient import TestClient

from app.main import app
from app.observability import JsonLogFormatter


client = TestClient(app)


def test_request_id_is_generated_and_returned():
    response = client.get("/health")
    assert response.status_code == 200
    assert re.fullmatch(r"[a-f0-9]{32}", response.headers["X-Request-ID"])


def test_valid_request_id_is_preserved():
    response = client.get("/health", headers={"X-Request-ID": "trace-123"})
    assert response.headers["X-Request-ID"] == "trace-123"


def test_invalid_request_id_is_replaced():
    response = client.get("/health", headers={"X-Request-ID": "bad value"})
    assert response.headers["X-Request-ID"] != "bad value"


def test_json_formatter_uses_allowlisted_fields_only():
    record = logging.LogRecord(
        "app.test", logging.INFO, __file__, 1, "request completed", (), None
    )
    record.request_id = "trace-123"
    record.api_key = "must-not-be-logged"
    payload = json.loads(JsonLogFormatter().format(record))
    assert payload["request_id"] == "trace-123"
    assert "api_key" not in payload
    assert "must-not-be-logged" not in json.dumps(payload)

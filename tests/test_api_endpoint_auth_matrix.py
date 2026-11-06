from __future__ import annotations

import re
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


PUBLIC_OPERATIONS = {("GET", "/health")}


def _resolve_schema(schema: dict, components: dict) -> dict:
    reference = schema.get("$ref")
    if reference:
        name = reference.rsplit("/", 1)[-1]
        return _resolve_schema(components[name], components)
    if "allOf" in schema:
        merged = {}
        for part in schema["allOf"]:
            merged.update(_resolve_schema(part, components))
        merged.update({key: value for key, value in schema.items() if key != "allOf"})
        return merged
    return schema


def _sample(schema: dict, components: dict):
    schema = _resolve_schema(schema, components)
    if "default" in schema:
        return schema["default"]
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    for union_key in ("anyOf", "oneOf"):
        if union_key in schema:
            candidates = [
                item for item in schema[union_key]
                if item.get("type") != "null"
            ]
            if candidates:
                return _sample(candidates[0], components)
    kind = schema.get("type")
    if kind == "object" or "properties" in schema:
        properties = schema.get("properties", {})
        required = schema.get("required", list(properties))
        return {
            name: _sample(properties[name], components)
            for name in required
            if name in properties
        }
    if kind == "array":
        minimum = int(schema.get("minItems", 0))
        return [_sample(schema.get("items", {}), components) for _ in range(minimum)]
    if kind == "string":
        fmt = schema.get("format")
        if fmt == "uuid":
            return str(UUID("00000000-0000-0000-0000-000000000001"))
        if fmt == "date-time":
            return "2026-01-01T00:00:00Z"
        pattern = schema.get("pattern", "")
        if "40" in pattern and "a-f" in pattern:
            return "a" * 40
        if "64" in pattern and "a-f" in pattern:
            return "a" * 64
        minimum = max(1, int(schema.get("minLength", 1)))
        return "x" * min(minimum, int(schema.get("maxLength", max(minimum, 1))))
    if kind == "integer":
        return int(schema.get("minimum", 1))
    if kind == "number":
        return float(schema.get("minimum", 1.0))
    if kind == "boolean":
        return False
    return None


def _operation_request(client, path, method, operation, components):
    parameters = list(operation.get("parameters", []))
    path_values = {}
    query_values = {}
    for parameter in parameters:
        value = _sample(parameter.get("schema", {}), components)
        if parameter.get("in") == "path":
            path_values[parameter["name"]] = value
        elif parameter.get("in") == "query":
            query_values[parameter["name"]] = value

    concrete_path = path
    for name, value in path_values.items():
        concrete_path = concrete_path.replace("{" + name + "}", str(value))

    body = None
    request_body = operation.get("requestBody", {})
    content_types = request_body.get("content", {})
    json_schema = content_types.get("application/json", {}).get("schema")
    if json_schema is not None:
        body = _sample(json_schema, components)

    return client.request(
        method,
        concrete_path,
        params=query_values,
        json=body,
        headers={"Idempotency-Key": "api-auth-matrix-0001"},
    )


@pytest.mark.security
def test_every_openapi_operation_rejects_missing_credentials_except_health(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "oidc")
    monkeypatch.setattr(settings, "environment", "test")
    monkeypatch.setattr(settings, "oidc_issuer", "https://identity.example.test/")
    monkeypatch.setattr(settings, "oidc_audience", "universal-generative-ai")
    monkeypatch.setattr(
        settings,
        "oidc_jwks_url",
        "https://identity.example.test/.well-known/jwks.json",
    )
    monkeypatch.setattr(settings, "external_worker_token", "configured-worker-secret")
    monkeypatch.setattr(settings, "worker_admin_token", "configured-admin-secret")

    schema = app.openapi()
    components = schema.get("components", {}).get("schemas", {})
    client = TestClient(app)
    checked = []

    for path, path_item in schema["paths"].items():
        for method, operation in path_item.items():
            verb = method.upper()
            if verb not in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}:
                continue
            if (verb, path) in PUBLIC_OPERATIONS:
                continue

            response = _operation_request(client, path, verb, operation, components)
            checked.append(f"{verb} {path}")
            assert response.status_code == 401, (
                f"{verb} {path} must reject a request without credentials; "
                f"received HTTP {response.status_code}: {response.text[:300]}"
            )

    assert checked, "The API security matrix did not discover any protected operations"

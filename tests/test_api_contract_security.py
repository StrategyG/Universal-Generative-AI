from __future__ import annotations

from app.main import app


HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}
INTENTIONALLY_PUBLIC = {("get", "/health")}
CUSTOM_AUTH_HEADERS = {
    "authorization",
    "x-worker-token",
    "x-worker-admin-token",
}


def test_every_openapi_operation_has_a_documented_response_contract():
    schema = app.openapi()
    operation_ids = []

    for path, path_item in schema["paths"].items():
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS:
                continue
            operation_id = operation.get("operationId")
            assert isinstance(operation_id, str) and operation_id.strip(), (
                f"{method.upper()} {path} is missing an operationId"
            )
            assert operation.get("responses"), (
                f"{method.upper()} {path} is missing response documentation"
            )
            operation_ids.append(operation_id)

    assert len(operation_ids) == len(set(operation_ids)), "OpenAPI operationId values must be unique"


def test_every_non_public_api_operation_declares_an_authentication_boundary():
    schema = app.openapi()
    uncovered = []

    for path, path_item in schema["paths"].items():
        for method, operation in path_item.items():
            method = method.lower()
            if method not in HTTP_METHODS or (method, path) in INTENTIONALLY_PUBLIC:
                continue

            bearer_security = bool(operation.get("security"))
            header_parameters = {
                str(parameter.get("name", "")).lower()
                for parameter in operation.get("parameters", [])
                if parameter.get("in") == "header"
            }
            custom_header_security = bool(header_parameters & CUSTOM_AUTH_HEADERS)
            if not (bearer_security or custom_header_security):
                uncovered.append(f"{method.upper()} {path}")

    assert not uncovered, (
        "Sensitive API operations without a documented authentication boundary: "
        + ", ".join(sorted(uncovered))
    )

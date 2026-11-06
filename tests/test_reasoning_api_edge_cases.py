from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.auth import Principal
from app.config import settings
from app.providers.text_errors import TextGenerationProviderError
from app.reasoning.api import ReasoningCompletionRequest, complete_reasoning
from app.reasoning.catalog import ReasoningRouteCatalogError
from app.reasoning.execution import (
    ReasoningEvaluatorUnavailable,
    ReasoningRouteConfigurationError,
)
from app.reasoning.routing import NoEligibleModelRoute


def make_request():
    return ReasoningCompletionRequest(
        project_id="project-1",
        domain="coding",
        objective="Exercise reasoning failure paths",
        context="Test context",
    )


def principal():
    return Principal(
        subject="user-1",
        tenant_id="tenant-1",
        roles=frozenset({"developer"}),
        project_ids=frozenset({"project-1"}),
        auth_mode="oidc",
    )


@pytest.mark.parametrize(
    ("error", "status_code", "error_code"),
    [
        (ReasoningRouteCatalogError("catalog missing"), 503, "reasoning_route_catalog_unavailable"),
        (ReasoningRouteConfigurationError("provider mismatch"), 503, "reasoning_route_policy_blocked"),
        (NoEligibleModelRoute("no safe route"), 503, "reasoning_route_policy_blocked"),
        (ReasoningEvaluatorUnavailable("review unavailable"), 503, "independent_evaluator_unavailable"),
        (TextGenerationProviderError("provider unavailable", code="provider_timeout", retryable=True), 502, "provider_timeout"),
        (RuntimeError("database unavailable"), 503, "reasoning_runtime_unavailable"),
    ],
)
def test_reasoning_endpoint_maps_dependency_failures_to_sanitized_http_contract(
    monkeypatch, error, status_code, error_code
):
    monkeypatch.setattr(
        "app.reasoning.api.TextModelRouter.from_settings",
        staticmethod(lambda: object()),
    )

    async def load_routes():
        return []

    class RaisingExecutor:
        def __init__(self, *, router, routes):
            raise error

    monkeypatch.setattr("app.reasoning.api.load_approved_text_routes", load_routes)
    monkeypatch.setattr("app.reasoning.api.PolicyRoutedTextExecutor", RaisingExecutor)

    with pytest.raises(HTTPException) as caught:
        asyncio.run(complete_reasoning(make_request(), principal()))
    assert caught.value.status_code == status_code
    assert caught.value.detail["code"] == error_code
    if error_code == "reasoning_runtime_unavailable":
        assert "database unavailable" not in str(caught.value.detail)


def test_reasoning_endpoint_requires_configured_permitted_data_regions(monkeypatch):
    monkeypatch.setattr(settings, "reasoning_permitted_data_regions", "")
    monkeypatch.setattr(
        "app.reasoning.api.TextModelRouter.from_settings",
        staticmethod(lambda: object()),
    )

    async def load_routes():
        return []

    class FakeExecutor:
        def __init__(self, *, router, routes):
            pass

    monkeypatch.setattr("app.reasoning.api.load_approved_text_routes", load_routes)
    monkeypatch.setattr("app.reasoning.api.PolicyRoutedTextExecutor", FakeExecutor)

    with pytest.raises(HTTPException) as caught:
        asyncio.run(complete_reasoning(make_request(), principal()))
    assert caught.value.status_code == 503
    assert caught.value.detail["code"] == "reasoning_regions_not_configured"

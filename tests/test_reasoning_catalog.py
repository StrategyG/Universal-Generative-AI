from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.config import settings
from app.reasoning.catalog import (
    ReasoningRouteCatalogError,
    load_approved_text_routes,
)
from app.reasoning.schemas import ModelRole


def entry(
    route_id: str,
    role: str,
    provider: str,
    family: str,
    *,
    revision: str | None = None,
):
    return {
        "route_id": route_id,
        "role": role,
        "provider": provider,
        "model_id": f"{provider}-model-id",
        "model_revision": revision or ("a" * 40),
        "model_family": family,
        "capabilities": ["text", "structured_output"],
        "data_regions": ["ap-southeast-1"],
        "max_context_tokens": 64_000,
        "quality_rank": 95,
        "estimated_input_cost_per_million": 1.0,
        "estimated_output_cost_per_million": 2.0,
    }


@pytest.fixture
def set_catalog(monkeypatch):
    def apply(value):
        monkeypatch.setattr(
            settings,
            "reasoning_route_catalog_json",
            json.dumps(value) if not isinstance(value, str) else value,
        )
    return apply


@pytest.mark.asyncio
async def test_catalog_requires_operator_configuration(monkeypatch):
    monkeypatch.setattr(settings, "reasoning_route_catalog_json", "")

    with pytest.raises(ReasoningRouteCatalogError, match="not_configured"):
        await load_approved_text_routes()


@pytest.mark.asyncio
async def test_catalog_rejects_invalid_json(set_catalog):
    set_catalog("{not-json")

    with pytest.raises(ReasoningRouteCatalogError, match="invalid_json"):
        await load_approved_text_routes()


@pytest.mark.asyncio
async def test_catalog_sets_approval_only_after_registry_success(monkeypatch, set_catalog):
    set_catalog([entry("primary", "reasoning_primary", "provider-a", "family-a")])
    calls = []

    async def approved(model_id, revision):
        calls.append((model_id, revision))
        return SimpleNamespace(
            model_id=model_id,
            revision=revision,
            family="family-a",
            status="approved",
            license_review_status="approved",
            validation_status="passed",
        )

    monkeypatch.setattr(
        "app.services.external_gpu_queue.assert_model_approved",
        approved,
    )
    routes = await load_approved_text_routes()

    assert calls == [("provider-a-model-id", "a" * 40)]
    assert routes[0].role is ModelRole.REASONING_PRIMARY
    assert routes[0].approved is True
    assert routes[0].enabled is True


@pytest.mark.asyncio
async def test_catalog_does_not_trust_approval_flags_from_json(monkeypatch, set_catalog):
    item = entry("primary", "reasoning_primary", "provider-a", "family-a")
    item["approved"] = True
    item["enabled"] = True
    set_catalog([item])

    called = False

    async def approval_must_be_checked(model_id, revision):
        nonlocal called
        called = True
        return SimpleNamespace(
            model_id=model_id,
            revision=revision,
            family="family-a",
            status="pending_review",
            license_review_status="approved",
            validation_status="passed",
        )

    monkeypatch.setattr(
        "app.services.external_gpu_queue.assert_model_approved",
        approval_must_be_checked,
    )
    with pytest.raises(ReasoningRouteCatalogError, match="schema_invalid"):
        await load_approved_text_routes()
    assert called is False


@pytest.mark.asyncio
async def test_catalog_rejects_registry_family_or_identity_mismatch(monkeypatch, set_catalog):
    set_catalog([entry("primary", "reasoning_primary", "provider-a", "family-a")])

    async def wrong_registry_record(model_id, revision):
        return SimpleNamespace(
            model_id=model_id,
            revision=revision,
            family="different-family",
            status="approved",
            license_review_status="approved",
            validation_status="passed",
        )

    monkeypatch.setattr(
        "app.services.external_gpu_queue.assert_model_approved",
        wrong_registry_record,
    )
    with pytest.raises(ReasoningRouteCatalogError, match="does_not_match_route"):
        await load_approved_text_routes()


@pytest.mark.asyncio
async def test_catalog_rejects_duplicate_route_ids(set_catalog):
    set_catalog(
        [
            entry("duplicate", "reasoning_primary", "provider-a", "family-a"),
            entry("duplicate", "reasoning_fallback", "provider-b", "family-b"),
        ]
    )
    with pytest.raises(ReasoningRouteCatalogError, match="unique"):
        await load_approved_text_routes()


@pytest.mark.asyncio
async def test_catalog_requires_primary_route(set_catalog):
    set_catalog([entry("fallback", "reasoning_fallback", "provider-b", "family-b")])

    async def approved(model_id, revision):
        return SimpleNamespace(
            model_id=model_id,
            revision=revision,
            family="family-b",
            status="approved",
            license_review_status="approved",
            validation_status="passed",
        )

    import app.services.external_gpu_queue

    app.services.external_gpu_queue.assert_model_approved = approved
    with pytest.raises(ReasoningRouteCatalogError, match="requires_primary"):
        await load_approved_text_routes()

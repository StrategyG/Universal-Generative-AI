"""Load an operator-declared reasoning route catalog against approved registry records."""

from __future__ import annotations

import json
from typing import Any

from pydantic import Field, FiniteFloat, ValidationError

from app.config import settings
from app.reasoning.routing import ModelRouteDescriptor
from app.reasoning.schemas import ModelRole, StrictContract


class ModelRouteCatalogEntry(StrictContract):
    """Non-secret routing metadata; registry approval is never read from this JSON."""

    route_id: str = Field(min_length=1, max_length=120)
    role: ModelRole
    provider: str = Field(min_length=1, max_length=120)
    model_id: str = Field(min_length=3, max_length=256)
    model_revision: str = Field(pattern=r"^[0-9a-fA-F]{40}$")
    model_family: str = Field(min_length=1, max_length=120)
    capabilities: set[str] = Field(min_length=1, max_length=32)
    data_regions: set[str] = Field(min_length=1, max_length=32)
    max_context_tokens: int = Field(ge=1)
    quality_rank: int = Field(ge=1, le=100)
    estimated_input_cost_per_million: FiniteFloat = Field(ge=0.0)
    estimated_output_cost_per_million: FiniteFloat = Field(ge=0.0)


class ReasoningRouteCatalogError(RuntimeError):
    """The configured route catalog cannot be safely loaded."""


_ALLOWED_TEXT_ROLES = {
    ModelRole.REASONING_PRIMARY,
    ModelRole.REASONING_FALLBACK,
    ModelRole.INDEPENDENT_EVALUATOR,
}


async def load_approved_text_routes() -> list[ModelRouteDescriptor]:
    """Resolve configured text routes and verify each immutable revision in registry.

    The JSON setting contains only operator-controlled routing metadata. It cannot
    grant approval or enable a model: those flags are set only after the canonical
    PostgreSQL model registry confirms approved status, license review and validation.
    """
    raw = settings.reasoning_route_catalog_json.strip()
    if not raw:
        raise ReasoningRouteCatalogError("reasoning_route_catalog_not_configured")

    try:
        payload: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReasoningRouteCatalogError("reasoning_route_catalog_invalid_json") from exc

    if not isinstance(payload, list) or not payload or len(payload) > 32:
        raise ReasoningRouteCatalogError("reasoning_route_catalog_must_be_1_to_32_entries")

    entries: list[ModelRouteCatalogEntry] = []
    try:
        entries = [ModelRouteCatalogEntry.model_validate(item) for item in payload]
    except ValidationError as exc:
        raise ReasoningRouteCatalogError("reasoning_route_catalog_schema_invalid") from exc

    route_ids = [entry.route_id for entry in entries]
    if len(route_ids) != len(set(route_ids)):
        raise ReasoningRouteCatalogError("reasoning_route_ids_must_be_unique")
    if any(entry.role not in _ALLOWED_TEXT_ROLES for entry in entries):
        raise ReasoningRouteCatalogError("reasoning_route_catalog_contains_non_text_role")
    if any("text" not in entry.capabilities for entry in entries):
        raise ReasoningRouteCatalogError("reasoning_text_route_must_declare_text_capability")

    from app.services.external_gpu_queue import assert_model_approved

    resolved: list[ModelRouteDescriptor] = []
    for entry in entries:
        try:
            registered = await assert_model_approved(entry.model_id, entry.model_revision)
        except Exception as exc:
            raise ReasoningRouteCatalogError(
                f"model_registry_approval_failed:{entry.route_id}"
            ) from exc

        registered_revision = str(getattr(registered, "revision", ""))
        registered_status = getattr(registered, "status", None)
        registered_status = getattr(registered_status, "value", registered_status)
        if (
            getattr(registered, "model_id", None) != entry.model_id
            or registered_revision.lower() != entry.model_revision.lower()
            or str(registered_status).lower() != "approved"
            or getattr(registered, "license_review_status", None) != "approved"
            or getattr(registered, "validation_status", None) != "passed"
            or getattr(registered, "family", None) != entry.model_family
        ):
            raise ReasoningRouteCatalogError(
                f"model_registry_record_does_not_match_route:{entry.route_id}"
            )

        resolved.append(
            ModelRouteDescriptor.model_validate(
                {
                    **entry.model_dump(),
                    "approved": True,
                    "enabled": True,
                }
            )
        )

    primary_count = sum(
        route.role is ModelRole.REASONING_PRIMARY for route in resolved
    )
    if primary_count == 0:
        raise ReasoningRouteCatalogError("reasoning_route_catalog_requires_primary")
    return resolved

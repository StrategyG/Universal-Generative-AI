"""Strict request and response schemas for the UGAI durable task API."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

IntentText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4_000),
]
CapabilityName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_.:-]*$",
    ),
]


class ArtifactReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str = Field(min_length=1, max_length=128)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    media_type: str = Field(min_length=1, max_length=128)


class TaskSubmission(BaseModel):
    """User intent and immutable references; actor and tenant are never accepted here."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: IntentText
    context: str = Field(default="", max_length=20_000)
    workspace_id: UUID
    notebook_id: UUID | None = None
    cell_revision: str | None = Field(default=None, max_length=128)
    artifacts: tuple[ArtifactReference, ...] = Field(default=(), max_length=32)
    requested_capabilities: tuple[CapabilityName, ...] = Field(default=(), max_length=32)

    @field_validator("requested_capabilities")
    @classmethod
    def capabilities_must_be_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("requested_capabilities_must_be_unique")
        return value


class TaskReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    request_id: UUID
    state: str
    created_at: str


class TaskStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    request_id: UUID
    state: str
    result_reference: str | None = Field(default=None, max_length=512)
    error_code: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_:-]{0,127}$")

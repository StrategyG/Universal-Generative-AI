from __future__ import annotations

from app.auth import Principal
from app.reasoning.api import ReasoningCompletionRequest


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

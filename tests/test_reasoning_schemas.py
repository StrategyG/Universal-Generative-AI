import pytest
from pydantic import ValidationError

from app.reasoning.schemas import (
    EvidenceReference,
    ModelRole,
    ModelStageTrace,
    ReasoningArtifact,
    ReasoningProfile,
    ReasoningStage,
    RiskTier,
)


def evidence():
    return EvidenceReference(
        evidence_id="ev-1",
        source_id="source-1",
        locator="https://example.invalid/document/1",
        sha256="a" * 64,
        independence_group="publisher-1",
        relevance=0.9,
    )


def test_reasoning_artifact_accepts_versioned_evidence_and_model_trace():
    item = ReasoningArtifact(
        request_id="req-1",
        tenant_id="tenant-1",
        project_id="project-1",
        policy_version="policy-1",
        risk_tier=RiskTier.HIGH,
        profile=ReasoningProfile.CRITICAL,
        stages_completed=[ReasoningStage.ANALYZE, ReasoningStage.EVALUATE],
        model_traces=[
            ModelStageTrace(
                stage=ReasoningStage.ANALYZE,
                role=ModelRole.REASONING_PRIMARY,
                provider="provider-a",
                model_id="model-a",
                model_revision="rev-1",
                latency_ms=1200,
            )
        ],
        evidence=[evidence()],
        rationale_summary="Two independent facts support the limited conclusion.",
        conclusion="Proceed only after the missing condition is verified.",
        correlation_id="trace-1",
        approval_required=True,
    )

    assert item.schema_version == "1.0"
    assert item.evidence[0].sha256 == "a" * 64
    assert item.approval_required is True


def test_evidence_rejects_malformed_sha256():
    with pytest.raises(ValidationError):
        EvidenceReference(
            evidence_id="ev-1",
            source_id="source-1",
            locator="doc:1",
            sha256="not-a-digest",
            independence_group="source-1",
            relevance=0.5,
        )


def test_artifact_rejects_unrecognized_fields_and_chain_of_thought():
    with pytest.raises(ValidationError):
        ReasoningArtifact(
            request_id="req-1",
            tenant_id="tenant-1",
            project_id="project-1",
            policy_version="p1",
            risk_tier="low",
            profile="standard",
            rationale_summary="summary",
            conclusion="answer",
            correlation_id="trace-1",
            chain_of_thought="private internal reasoning",
        )


def test_model_trace_requires_immutable_revision():
    with pytest.raises(ValidationError):
        ModelStageTrace(
            stage="analyze",
            role="reasoning_primary",
            provider="provider-a",
            model_id="model-a",
            model_revision="",
            latency_ms=100,
        )

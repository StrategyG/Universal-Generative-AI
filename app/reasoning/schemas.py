from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelRole(str, Enum):
    REASONING_PRIMARY = "reasoning_primary"
    REASONING_FALLBACK = "reasoning_fallback"
    INDEPENDENT_EVALUATOR = "independent_evaluator"
    FAST_CLASSIFIER = "fast_classifier"
    EMBEDDING = "embedding"
    RERANKER = "reranker"
    MULTIMODAL_READER = "multimodal_reader"


class ReasoningProfile(str, Enum):
    STANDARD = "standard"
    DEEP = "deep"
    CRITICAL = "critical"


class RiskTier(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class ReasoningStage(str, Enum):
    OBSERVE = "observe"
    ANALYZE = "analyze"
    RETRIEVE = "retrieve"
    EVALUATE = "evaluate"
    CHALLENGE = "challenge"
    SYNTHESIZE = "synthesize"
    DECIDE = "decide"
    VERIFY = "verify"


class VerificationStatus(str, Enum):
    NOT_RUN = "not_run"
    PASSED = "passed"
    FAILED = "failed"
    NEEDS_HUMAN_REVIEW = "needs_human_review"


class FindingSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    BLOCKER = "blocker"


class EvidenceReference(StrictContract):
    evidence_id: str = Field(min_length=1, max_length=160)
    source_id: str = Field(min_length=1, max_length=160)
    locator: str = Field(min_length=1, max_length=2048)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_timestamp: str | None = Field(default=None, max_length=64)
    independence_group: str = Field(min_length=1, max_length=160)
    relevance: float = Field(ge=0.0, le=1.0)


class SupportedClaim(StrictContract):
    claim_id: str = Field(min_length=1, max_length=160)
    statement: str = Field(min_length=1, max_length=4000)
    evidence_ids: list[str] = Field(min_length=1, max_length=50)
    material: bool = True


class Assumption(StrictContract):
    assumption_id: str = Field(min_length=1, max_length=160)
    statement: str = Field(min_length=1, max_length=2000)
    impact_if_false: str = Field(min_length=1, max_length=1000)


class Counterargument(StrictContract):
    statement: str = Field(min_length=1, max_length=3000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)
    disposition: str = Field(min_length=1, max_length=1000)


class EvaluationFinding(StrictContract):
    category: str = Field(min_length=1, max_length=120)
    severity: FindingSeverity
    description: str = Field(min_length=1, max_length=3000)
    related_claim_ids: list[str] = Field(default_factory=list, max_length=50)
    remediation: str | None = Field(default=None, max_length=1500)


class DecisionOption(StrictContract):
    option_id: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=2000)
    criteria_scores: dict[str, FiniteFloat] = Field(default_factory=dict)
    expected_value: FiniteFloat | None = None
    downside: str | None = Field(default=None, max_length=2000)
    reversibility: str = Field(min_length=1, max_length=500)


class ModelStageTrace(StrictContract):
    stage: ReasoningStage
    role: ModelRole
    provider: str = Field(min_length=1, max_length=120)
    model_id: str = Field(min_length=1, max_length=200)
    model_revision: str = Field(min_length=1, max_length=200)
    latency_ms: int = Field(ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    fallback_used: bool = False


class VerificationRecord(StrictContract):
    status: VerificationStatus = VerificationStatus.NOT_RUN
    checks: list[str] = Field(default_factory=list, max_length=100)
    failures: list[str] = Field(default_factory=list, max_length=100)
    verified_by: str | None = Field(default=None, max_length=200)


class ReasoningRequestContext(StrictContract):
    """Internal context. tenant_id and actor_id must come from verified server identity."""

    request_id: str = Field(min_length=1, max_length=160)
    tenant_id: str = Field(min_length=1, max_length=160)
    project_id: str = Field(min_length=1, max_length=160)
    actor_id: str = Field(min_length=1, max_length=160)
    policy_version: str = Field(min_length=1, max_length=100)
    risk_tier: RiskTier
    profile: ReasoningProfile = ReasoningProfile.STANDARD
    objective: str = Field(min_length=1, max_length=8000)
    constraints: list[str] = Field(default_factory=list, max_length=100)


class ReasoningArtifact(StrictContract):
    schema_version: str = "1.0"
    request_id: str = Field(min_length=1, max_length=160)
    tenant_id: str = Field(min_length=1, max_length=160)
    project_id: str = Field(min_length=1, max_length=160)
    policy_version: str = Field(min_length=1, max_length=100)
    risk_tier: RiskTier
    profile: ReasoningProfile
    stages_completed: list[ReasoningStage] = Field(default_factory=list, max_length=8)
    model_traces: list[ModelStageTrace] = Field(default_factory=list, max_length=32)
    evidence: list[EvidenceReference] = Field(default_factory=list, max_length=500)
    claims: list[SupportedClaim] = Field(default_factory=list, max_length=250)
    assumptions: list[Assumption] = Field(default_factory=list, max_length=100)
    counterarguments: list[Counterargument] = Field(default_factory=list, max_length=100)
    options: list[DecisionOption] = Field(default_factory=list, max_length=50)
    findings: list[EvaluationFinding] = Field(default_factory=list, max_length=200)
    rationale_summary: str = Field(min_length=1, max_length=6000)
    conclusion: str = Field(min_length=1, max_length=6000)
    limitations: list[str] = Field(default_factory=list, max_length=100)
    calibrated_confidence: FiniteFloat | None = Field(default=None, ge=0.0, le=1.0)
    verification: VerificationRecord = Field(default_factory=VerificationRecord)
    approval_required: bool = False
    correlation_id: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_artifact_references(self) -> "ReasoningArtifact":
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("reasoning_artifact_duplicate_evidence_ids")

        claim_ids = [item.claim_id for item in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("reasoning_artifact_duplicate_claim_ids")

        assumption_ids = [item.assumption_id for item in self.assumptions]
        if len(assumption_ids) != len(set(assumption_ids)):
            raise ValueError("reasoning_artifact_duplicate_assumption_ids")

        option_ids = [item.option_id for item in self.options]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("reasoning_artifact_duplicate_option_ids")

        if len(self.stages_completed) != len(set(self.stages_completed)):
            raise ValueError("reasoning_artifact_duplicate_completed_stages")

        known_evidence = set(evidence_ids)
        for claim in self.claims:
            if not set(claim.evidence_ids).issubset(known_evidence):
                raise ValueError(f"claim_references_unknown_evidence:{claim.claim_id}")

        for counterargument in self.counterarguments:
            if not set(counterargument.evidence_ids).issubset(known_evidence):
                raise ValueError("counterargument_references_unknown_evidence")

        known_claims = set(claim_ids)
        for finding in self.findings:
            if not set(finding.related_claim_ids).issubset(known_claims):
                raise ValueError("finding_references_unknown_claim")

        return self

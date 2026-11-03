"""Typed, validated input and output contracts for decision intelligence."""
from __future__ import annotations
from dataclasses import dataclass, field
import math


def _required_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _unit_interval(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number between 0 and 1")
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{name} must be a finite number between 0 and 1")


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """One attributable observation; evidence is data, never executable instruction.

    Records with the same independence_group are treated as correlated. The
    engine counts only the strongest record in each group for sufficiency.
    """
    evidence_id: str
    topic: str
    position: str
    source_id: str
    independence_group: str
    source_reliability: float
    evidence_quality: float
    relevance: float
    freshness: float
    verified: bool = False
    provenance_uri: str | None = None

    def __post_init__(self) -> None:
        for name in ("evidence_id", "topic", "position", "source_id", "independence_group"):
            _required_text(name, getattr(self, name))
        for name in ("source_reliability", "evidence_quality", "relevance", "freshness"):
            _unit_interval(name, getattr(self, name))
        if not isinstance(self.verified, bool):
            raise ValueError("verified must be a boolean")
        if self.provenance_uri is not None and not isinstance(self.provenance_uri, str):
            raise ValueError("provenance_uri must be a string or None")


@dataclass(frozen=True, slots=True)
class StrategicOption:
    """A proposed strategic action; estimates must come from upstream analysis."""
    option_id: str
    name: str
    role: str
    evidence_ids: tuple[str, ...]
    expected_upside: float = 0.0
    probability_success: float = 0.5
    downside_loss: float = 0.0
    strategic_fit: float = 0.5
    cost: float = 0.0
    reversibility: float = 0.5
    risk_mitigation: float = 0.0
    max_allocation: float = 0.35

    def __post_init__(self) -> None:
        _required_text("option_id", self.option_id)
        _required_text("name", self.name)
        if self.role not in {"hedge", "bet"}:
            raise ValueError("role must be 'hedge' or 'bet'")
        if not isinstance(self.evidence_ids, tuple):
            raise ValueError("evidence_ids must be a tuple")
        if any(not isinstance(item, str) or not item.strip() for item in self.evidence_ids):
            raise ValueError("evidence_ids must contain non-empty strings")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("evidence_ids must not contain duplicates")
        for name in ("expected_upside", "probability_success", "downside_loss", "strategic_fit", "cost", "reversibility", "risk_mitigation", "max_allocation"):
            _unit_interval(name, getattr(self, name))


@dataclass(frozen=True, slots=True)
class DecisionRequest:
    """A bounded decision problem, including explicit holistic context."""
    question: str
    evidence: tuple[EvidenceItem, ...]
    options: tuple[StrategicOption, ...]
    system_factors: tuple[str, ...] = field(default_factory=tuple)
    stakeholder_impacts: tuple[str, ...] = field(default_factory=tuple)
    time_horizons: tuple[str, ...] = ("short_term", "long_term")
    assumptions: tuple[str, ...] = field(default_factory=tuple)
    risk_tolerance: str = "balanced"
    evidence_threshold: float = 0.50
    reserve_floor: float = 0.15
    hedge_target: float = 0.20
    max_bet_allocation: float = 0.25
    risk_budget: float = 0.25

    def __post_init__(self) -> None:
        _required_text("question", self.question)
        if not isinstance(self.evidence, tuple) or not isinstance(self.options, tuple):
            raise ValueError("evidence and options must be tuples")
        if not all(isinstance(item, EvidenceItem) for item in self.evidence):
            raise ValueError("evidence must contain EvidenceItem values")
        if not all(isinstance(item, StrategicOption) for item in self.options):
            raise ValueError("options must contain StrategicOption values")
        evidence_ids = [item.evidence_id for item in self.evidence]
        option_ids = [item.option_id for item in self.options]
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("evidence_id values must be unique")
        if len(set(option_ids)) != len(option_ids):
            raise ValueError("option_id values must be unique")
        known_ids = set(evidence_ids)
        for option in self.options:
            if set(option.evidence_ids) - known_ids:
                raise ValueError(f"option {option.option_id!r} references unknown evidence IDs")
        for field_name in ("system_factors", "stakeholder_impacts", "time_horizons", "assumptions"):
            values = getattr(self, field_name)
            if not isinstance(values, tuple) or any(not isinstance(value, str) or not value.strip() for value in values):
                raise ValueError(f"{field_name} must be a tuple of non-empty strings")
        if self.risk_tolerance not in {"defensive", "balanced", "opportunity_seeking"}:
            raise ValueError("risk_tolerance must be defensive, balanced, or opportunity_seeking")
        for name in ("evidence_threshold", "reserve_floor", "hedge_target", "max_bet_allocation", "risk_budget"):
            _unit_interval(name, getattr(self, name))
        if self.reserve_floor + self.hedge_target > 1:
            raise ValueError("reserve_floor + hedge_target must not exceed 1")


@dataclass(frozen=True, slots=True)
class OptionAssessment:
    option_id: str
    role: str
    score: float
    evidence_coverage: float
    expected_value: float | None
    conflict_topics: tuple[str, ...]
    rationale: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PortfolioAllocation:
    option_id: str
    role: str
    allocation: float
    downside_contribution: float


@dataclass(frozen=True, slots=True)
class DecisionResult:
    status: str
    evidence_quality_score: float
    evidence_sufficiency_score: float
    independent_source_count: int
    conflict_topics: tuple[str, ...]
    assessments: tuple[OptionAssessment, ...]
    allocations: tuple[PortfolioAllocation, ...]
    reserve_allocation: float
    expected_gross_downside: float
    expected_net_downside_after_hedge: float
    human_approval_required: bool
    confidence_type: str
    analysis_summary: tuple[str, ...]
    holistic_review: tuple[str, ...]
    caveats: tuple[str, ...]

    def allocation_for(self, option_id: str) -> float:
        """Return selected allocation, or zero when the option was not selected."""
        return next((item.allocation for item in self.allocations if item.option_id == option_id), 0.0)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable structure for workflow/API boundaries."""
        return {
            "status": self.status,
            "evidence_quality_score": self.evidence_quality_score,
            "evidence_sufficiency_score": self.evidence_sufficiency_score,
            "independent_source_count": self.independent_source_count,
            "conflict_topics": list(self.conflict_topics),
            "assessments": [
                {"option_id": x.option_id, "role": x.role, "score": x.score,
                 "evidence_coverage": x.evidence_coverage, "expected_value": x.expected_value,
                 "conflict_topics": list(x.conflict_topics), "rationale": list(x.rationale)}
                for x in self.assessments
            ],
            "allocations": [
                {"option_id": x.option_id, "role": x.role, "allocation": x.allocation,
                 "downside_contribution": x.downside_contribution}
                for x in self.allocations
            ],
            "reserve_allocation": self.reserve_allocation,
            "expected_gross_downside": self.expected_gross_downside,
            "expected_net_downside_after_hedge": self.expected_net_downside_after_hedge,
            "human_approval_required": self.human_approval_required,
            "confidence_type": self.confidence_type,
            "analysis_summary": list(self.analysis_summary),
            "holistic_review": list(self.holistic_review),
            "caveats": list(self.caveats),
        }

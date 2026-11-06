from __future__ import annotations

import pytest

from ugai_decision import DecisionEngine, DecisionRequest, EvidenceItem, StrategicOption
from ugai_decision.engine import _water_fill


def evidence(evidence_id: str, source: str, group: str) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        topic="market_demand",
        position="positive",
        source_id=source,
        independence_group=group,
        source_reliability=0.95,
        evidence_quality=0.95,
        relevance=0.95,
        freshness=0.95,
        verified=True,
    )


def option(option_id: str, role: str, *, max_allocation: float = 0.35) -> StrategicOption:
    return StrategicOption(
        option_id=option_id,
        name=option_id,
        role=role,
        evidence_ids=("e1", "e2", "e3"),
        expected_upside=0.8,
        probability_success=0.7,
        downside_loss=0.3,
        strategic_fit=0.9,
        cost=0.2,
        reversibility=0.8,
        risk_mitigation=0.85 if role == "hedge" else 0.0,
        max_allocation=max_allocation,
    )


def make_request(**overrides: object) -> DecisionRequest:
    values: dict[str, object] = {
        "question": "Should the organization enter this market?",
        "evidence": (
            evidence("e1", "report-a", "origin-a"),
            evidence("e2", "dataset-b", "origin-b"),
            evidence("e3", "filing-c", "origin-c"),
        ),
        "options": (
            option("hedge-1", "hedge"),
            option("bet-1", "bet"),
            option("bet-2", "bet"),
        ),
    }
    values.update(overrides)
    return DecisionRequest(**values)  # type: ignore[arg-type]


def test_water_fill_handles_zero_scores_empty_candidates_and_zero_capacity():
    assert _water_fill([], available=1.0, request_cap=0.5) == {}
    assert _water_fill([(option("zero", "bet"), 0.0)], available=1.0, request_cap=0.5) == {}
    assert _water_fill([(option("positive", "bet"), 0.8)], available=0.0, request_cap=0.5) == {"positive": 0.0}


def test_water_fill_caps_each_option_then_redistributes_remaining_capacity():
    first = option("first", "bet", max_allocation=0.1)
    second = option("second", "bet", max_allocation=0.8)
    result = _water_fill([(first, 0.8), (second, 0.2)], available=0.7, request_cap=0.8)
    assert result["first"] == pytest.approx(0.1)
    assert result["second"] == pytest.approx(0.6)
    assert sum(result.values()) == pytest.approx(0.7)


def test_zero_hedge_target_and_zero_risk_budget_keep_recommendation_under_review():
    request = make_request(hedge_target=0.0, risk_budget=0.0)
    result = DecisionEngine().evaluate(request)
    assert result.status == "REVIEW_REQUIRED"
    assert result.expected_gross_downside == 0.0
    assert result.expected_net_downside_after_hedge == 0.0
    assert result.human_approval_required is True


@pytest.mark.parametrize("risk_tolerance", ["defensive", "balanced", "opportunity_seeking"])
def test_option_assessment_covers_all_risk_tolerance_branches(risk_tolerance):
    result = DecisionEngine().evaluate(make_request(risk_tolerance=risk_tolerance))
    assert result.assessments
    assert all(0.0 <= item.score <= 1.0 for item in result.assessments)


def test_empty_optional_holistic_context_is_reported_without_invention():
    result = DecisionEngine().evaluate(
        make_request(system_factors=(), stakeholder_impacts=(), assumptions=(), time_horizons=())
    )
    assert any("not supplied" in item for item in result.holistic_review)
    assert any("none declared" in item for item in result.holistic_review)

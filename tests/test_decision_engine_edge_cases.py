from __future__ import annotations

import pytest

from ugai_decision import DecisionEngine
from ugai_decision.engine import _water_fill
from tests.test_decision_engine import good_evidence, make_request, option


def test_water_fill_handles_zero_scores_empty_candidates_and_zero_capacity():
    assert _water_fill([], available=1.0, request_cap=0.5) == {}
    assert _water_fill([(option("zero", "bet"), 0.0)], available=1.0, request_cap=0.5) == {}
    assert _water_fill([(option("positive", "bet"), 0.8)], available=0.0, request_cap=0.5) == {}


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


def test_option_assessment_covers_all_risk_tolerance_branches():
    for risk_tolerance in ("defensive", "balanced", "opportunity_seeking"):
        result = DecisionEngine().evaluate(make_request(risk_tolerance=risk_tolerance))
        assert result.assessments
        assert all(0.0 <= item.score <= 1.0 for item in result.assessments)


def test_empty_optional_holistic_context_is_reported_without_invention():
    result = DecisionEngine().evaluate(
        make_request(system_factors=(), stakeholder_impacts=(), assumptions=(), time_horizons=())
    )
    assert any("not supplied" in item for item in result.holistic_review)
    assert any("none declared" in item for item in result.holistic_review)

import pytest

from ugai_decision import DecisionEngine, DecisionRequest, EvidenceItem, StrategicOption


def evidence(evidence_id: str, source: str, group: str, *, topic: str = "market_demand",
             position: str = "positive", score: float = 0.95) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id, topic=topic, position=position, source_id=source,
        independence_group=group, source_reliability=score, evidence_quality=score,
        relevance=score, freshness=score, verified=True,
    )


def option(option_id: str, role: str, evidence_ids: tuple[str, ...] = ("e1", "e2", "e3"),
           **overrides: float) -> StrategicOption:
    values = {
        "expected_upside": 0.8, "probability_success": 0.7, "downside_loss": 0.3,
        "strategic_fit": 0.9, "cost": 0.2, "reversibility": 0.8,
        "risk_mitigation": 0.85 if role == "hedge" else 0.0, "max_allocation": 0.30,
    }
    values.update(overrides)
    return StrategicOption(option_id=option_id, name=option_id, role=role,
                           evidence_ids=evidence_ids, **values)


def good_evidence() -> tuple[EvidenceItem, ...]:
    return (
        evidence("e1", "report-a", "origin-a"),
        evidence("e2", "dataset-b", "origin-b"),
        evidence("e3", "filing-c", "origin-c"),
    )


def make_request(**overrides: object) -> DecisionRequest:
    values: dict[str, object] = {
        "question": "Should the organization enter this market?",
        "evidence": good_evidence(),
        "options": (
            option("hedge-1", "hedge"),
            option("bet-1", "bet"),
            option("bet-2", "bet", downside_loss=0.9),
        ),
        "system_factors": ("supplier dependencies", "regulatory exposure"),
        "stakeholder_impacts": ("employees", "customers", "partners"),
        "assumptions": ("cost estimates are provisional",),
    }
    values.update(overrides)
    return DecisionRequest(**values)  # type: ignore[arg-type]


def test_balanced_recommendation_is_bounded_and_requires_human_approval() -> None:
    result = DecisionEngine().evaluate(make_request())
    assert result.status == "RECOMMENDATION_READY"
    assert result.human_approval_required is True
    assert sum(item.allocation for item in result.allocations) + result.reserve_allocation == pytest.approx(1.0)
    assert result.expected_gross_downside <= 0.25 + 1e-9
    assert result.allocation_for("bet-1") <= 0.25
    assert result.allocation_for("bet-2") <= 0.25
    assert result.reserve_allocation >= 0.15
    assert result.expected_net_downside_after_hedge <= result.expected_gross_downside


def test_duplicate_derivative_sources_do_not_inflate_independence() -> None:
    duplicated = (
        evidence("e1", "mirror-a", "same-origin"),
        evidence("e2", "mirror-b", "same-origin"),
        evidence("e3", "mirror-c", "same-origin"),
    )
    result = DecisionEngine().evaluate(make_request(
        evidence=duplicated, options=(option("bet-only", "bet", ("e1", "e2", "e3")),)
    ))
    assert result.independent_source_count == 1
    assert result.status == "HOLD_FOR_EVIDENCE"
    assert result.reserve_allocation == 1.0
    assert result.allocations == ()


def test_low_evidence_fails_closed_to_reserve() -> None:
    result = DecisionEngine().evaluate(make_request(evidence=(), options=()))
    assert result.status == "HOLD_FOR_EVIDENCE"
    assert result.reserve_allocation == 1.0
    assert result.human_approval_required is True


def test_conflicting_independent_evidence_requires_review() -> None:
    conflicting = (
        evidence("e1", "report-a", "origin-a", position="positive"),
        evidence("e2", "audit-b", "origin-b", position="negative"),
        evidence("e3", "dataset-c", "origin-c", topic="cost", position="high"),
    )
    result = DecisionEngine().evaluate(make_request(
        evidence=conflicting,
        options=(option("hedge-1", "hedge"), option("bet-1", "bet")),
    ))
    assert "market_demand" in result.conflict_topics
    assert result.status == "REVIEW_REQUIRED"
    assert result.human_approval_required is True


def test_missing_hedge_is_explicitly_flagged() -> None:
    result = DecisionEngine().evaluate(make_request(options=(option("bet-1", "bet"),)))
    assert result.status == "REVIEW_REQUIRED"
    assert any("hedge coverage is absent" in item for item in result.caveats)


def test_unsupported_option_receives_zero_score_and_no_allocation() -> None:
    result = DecisionEngine().evaluate(make_request(options=(
        option("hedge-1", "hedge", ("e1", "e2", "e3")),
        option("bet-unsupported", "bet", ()),
    )))
    assert result.allocation_for("bet-unsupported") == 0.0
    assessment = next(item for item in result.assessments if item.option_id == "bet-unsupported")
    assert assessment.evidence_coverage == 0.0
    assert assessment.score == 0.0


def test_holistic_context_is_preserved_in_output() -> None:
    result = DecisionEngine().evaluate(make_request())
    assert any("supplier dependencies" in item for item in result.holistic_review)
    assert any("employees" in item for item in result.holistic_review)
    assert any("short_term" in item for item in result.holistic_review)


def test_confidence_is_explicitly_not_a_probability() -> None:
    result = DecisionEngine().evaluate(make_request())
    assert result.confidence_type == "evidence_sufficiency_heuristic_not_probability"
    assert "evidence_sufficiency_score" in result.to_dict()


@pytest.mark.parametrize("field,value", [
    ("source_reliability", 1.5),
    ("evidence_quality", float("nan")),
    ("freshness", -0.1),
])
def test_invalid_evidence_scores_are_rejected(field: str, value: float) -> None:
    values = {
        "evidence_id": "bad", "topic": "topic", "position": "claim",
        "source_id": "source", "independence_group": "group",
        "source_reliability": 0.5, "evidence_quality": 0.5,
        "relevance": 0.5, "freshness": 0.5,
    }
    values[field] = value
    with pytest.raises(ValueError):
        EvidenceItem(**values)  # type: ignore[arg-type]


def test_request_rejects_unknown_option_evidence_references() -> None:
    with pytest.raises(ValueError, match="unknown evidence IDs"):
        make_request(options=(option("bet-bad", "bet", ("missing",)),))

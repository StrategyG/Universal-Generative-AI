"""Deterministic evidence-led analysis, evaluation, holistic review and hedge-bet engine."""
from __future__ import annotations
from collections import defaultdict
from typing import Iterable

from .models import DecisionRequest, DecisionResult, EvidenceItem, OptionAssessment, PortfolioAllocation, StrategicOption

_EVIDENCE_WEIGHTS = {
    "source_reliability": 0.25,
    "evidence_quality": 0.25,
    "relevance": 0.20,
    "freshness": 0.15,
    "verified": 0.15,
}


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _evidence_item_score(item: EvidenceItem) -> float:
    """Transparent heuristic score; it is not a factual probability."""
    values = {
        "source_reliability": item.source_reliability,
        "evidence_quality": item.evidence_quality,
        "relevance": item.relevance,
        "freshness": item.freshness,
        "verified": 1.0 if item.verified else 0.5,
    }
    return sum(_EVIDENCE_WEIGHTS[key] * values[key] for key in _EVIDENCE_WEIGHTS)


def _water_fill(candidates: Iterable[tuple[StrategicOption, float]], available: float, request_cap: float) -> dict[str, float]:
    """Pro-rata allocation with per-option caps; deterministic and side-effect free."""
    rows = [(option, score) for option, score in candidates if score > 0]
    remaining = max(0.0, available)
    result = {option.option_id: 0.0 for option, _ in rows}
    active = list(rows)
    while active and remaining > 1e-12:
        total_score = sum(score for _, score in active)
        if total_score <= 0:
            break
        proposed = [(option, score, remaining * score / total_score) for option, score in active]
        capped_any = False
        next_active = []
        spent = 0.0
        for option, score, share in proposed:
            cap = min(option.max_allocation, request_cap)
            room = max(0.0, cap - result[option.option_id])
            amount = min(room, share)
            result[option.option_id] += amount
            spent += amount
            if room - amount > 1e-12:
                next_active.append((option, score))
            else:
                capped_any = True
        remaining -= spent
        if not capped_any or spent <= 1e-12:
            break
        active = next_active
    return result


class DecisionEngine:
    """Pure decision service; never invokes tools, spends funds or executes actions.

    Evidence sufficiency is a transparent heuristic index, not a calibrated
    probability. Every output requires a separate human approval step.
    """

    def evaluate(self, request: DecisionRequest) -> DecisionResult:
        evidence_by_id = {item.evidence_id: item for item in request.evidence}
        by_independence: dict[str, list[EvidenceItem]] = defaultdict(list)
        positions: dict[str, set[str]] = defaultdict(set)
        topic_groups: dict[str, set[str]] = defaultdict(set)
        for item in request.evidence:
            by_independence[item.independence_group].append(item)
            positions[item.topic].add(item.position)
            topic_groups[item.topic].add(item.independence_group)

        group_scores = [max(_evidence_item_score(item) for item in group) for group in by_independence.values()]
        quality_score = sum(group_scores) / len(group_scores) if group_scores else 0.0
        independent_count = len(by_independence)
        sufficiency_score = quality_score * min(1.0, independent_count / 3.0)
        conflicts = tuple(sorted(
            topic for topic, values in positions.items()
            if len(values) > 1 and len(topic_groups[topic]) > 1
        ))
        assessments = tuple(
            self._assess_option(option, evidence_by_id, set(conflicts), request)
            for option in request.options
        )
        if not request.evidence or sufficiency_score < request.evidence_threshold:
            return self._hold_for_evidence(request, quality_score, sufficiency_score, independent_count, conflicts, assessments)

        assessment_by_id = {item.option_id: item for item in assessments}
        hedge_candidates = [option for option in request.options
                            if option.role == "hedge" and assessment_by_id[option.option_id].score > 0]
        bet_candidates = [option for option in request.options
                          if option.role == "bet" and assessment_by_id[option.option_id].score > 0]

        selected_hedge = None
        hedge_allocation = 0.0
        if hedge_candidates and request.hedge_target > 0:
            selected_hedge = sorted(
                hedge_candidates,
                key=lambda item: (-assessment_by_id[item.option_id].score, item.option_id),
            )[0]
            hedge_allocation = min(request.hedge_target, selected_hedge.max_allocation, 1.0 - request.reserve_floor)

        bet_capacity = max(0.0, 1.0 - request.reserve_floor - hedge_allocation)
        bet_allocations = _water_fill(
            ((option, assessment_by_id[option.option_id].score) for option in bet_candidates),
            available=bet_capacity,
            request_cap=request.max_bet_allocation,
        )
        # Never use estimated hedge effectiveness to justify extra risky exposure.
        gross_downside = sum(bet_allocations.get(option.option_id, 0.0) * option.downside_loss
                             for option in bet_candidates)
        if gross_downside > request.risk_budget and gross_downside > 0:
            scale = request.risk_budget / gross_downside
            bet_allocations = {key: value * scale for key, value in bet_allocations.items()}

        allocation_rows = []
        if selected_hedge is not None and hedge_allocation > 0:
            allocation_rows.append(PortfolioAllocation(selected_hedge.option_id, "hedge", hedge_allocation, 0.0))
        for option in sorted(bet_candidates, key=lambda item: item.option_id):
            amount = bet_allocations.get(option.option_id, 0.0)
            if amount > 0:
                allocation_rows.append(PortfolioAllocation(
                    option.option_id, "bet", amount, amount * option.downside_loss
                ))

        allocated = sum(item.allocation for item in allocation_rows)
        reserve_allocation = _clamp(1.0 - allocated)
        expected_gross_downside = sum(item.downside_contribution for item in allocation_rows)
        hedge_effectiveness = selected_hedge.risk_mitigation * hedge_allocation if selected_hedge else 0.0
        expected_net_downside = expected_gross_downside * (1.0 - _clamp(hedge_effectiveness))
        missing_hedge = selected_hedge is None
        no_viable_bet = not any(bet_allocations.get(item.option_id, 0.0) > 0 for item in bet_candidates)
        status = "REVIEW_REQUIRED" if conflicts or missing_hedge or no_viable_bet else "RECOMMENDATION_READY"

        caveats = [
            "All numeric option estimates are upstream assumptions and require validation.",
            "Confidence is an evidence-sufficiency heuristic, not a calibrated success probability.",
            "Allocations are advisory only; this engine does not execute or transfer resources.",
            "Gross bet downside is constrained before hypothetical hedge benefit is considered.",
        ]
        if conflicts:
            caveats.append("Conflicting evidence remains unresolved for: " + ", ".join(conflicts))
        if missing_hedge:
            caveats.append("No evidence-supported hedge option was available; hedge coverage is absent.")
        if no_viable_bet:
            caveats.append("No bet option received a positive, evidence-supported allocation.")

        return DecisionResult(
            status=status,
            evidence_quality_score=quality_score,
            evidence_sufficiency_score=sufficiency_score,
            independent_source_count=independent_count,
            conflict_topics=conflicts,
            assessments=assessments,
            allocations=tuple(allocation_rows),
            reserve_allocation=reserve_allocation,
            expected_gross_downside=expected_gross_downside,
            expected_net_downside_after_hedge=expected_net_downside,
            human_approval_required=True,
            confidence_type="evidence_sufficiency_heuristic_not_probability",
            analysis_summary=(
                f"Evaluated {len(request.evidence)} evidence records across {independent_count} independent source groups.",
                f"Identified {len(positions)} evidence topics and {len(conflicts)} unresolved topic conflicts.",
                f"Assessed {len(request.options)} strategic options using expected value, fit, downside and reversibility.",
            ),
            holistic_review=self._holistic_review(request),
            caveats=tuple(caveats),
        )

    def _assess_option(self, option: StrategicOption, evidence_by_id: dict[str, EvidenceItem],
                       conflicts: set[str], request: DecisionRequest) -> OptionAssessment:
        linked = [evidence_by_id[item] for item in option.evidence_ids]
        linked_groups = {item.independence_group for item in linked}
        coverage = min(1.0, len(linked_groups) / 2.0)
        overlap = tuple(sorted({item.topic for item in linked if item.topic in conflicts}))
        conflict_penalty = min(0.50, 0.20 * len(overlap))
        risk_aversion = {"defensive": 0.20, "balanced": 0.12, "opportunity_seeking": 0.05}[request.risk_tolerance]
        expected_value = None
        if option.role == "bet":
            expected_value = option.probability_success * option.expected_upside - (1.0 - option.probability_success) * option.downside_loss
            normalized_value = (expected_value + 1.0) / 2.0
            base_score = (
                0.35 * option.strategic_fit + 0.30 * normalized_value
                + 0.20 * option.reversibility + 0.15 * (1.0 - option.downside_loss)
                - 0.15 * option.cost - risk_aversion * option.downside_loss
            )
            rationale = (
                "Expected value combines success-weighted upside and failure downside.",
                "Strategic fit, reversibility, cost and risk tolerance modify the opportunity score.",
            )
        else:
            base_score = (
                0.40 * option.risk_mitigation + 0.25 * option.strategic_fit
                + 0.15 * option.reversibility + 0.10 * option.probability_success
                + 0.10 * (1.0 - option.cost) - risk_aversion * option.cost
            )
            rationale = (
                "Hedge score emphasizes downside mitigation, strategic fit and reversibility.",
                "Hedge effectiveness is credited only when reporting net downside, not when expanding bet risk.",
            )
        score = _clamp(base_score) * coverage * (1.0 - conflict_penalty)
        reasons = list(rationale)
        if coverage < 1.0:
            reasons.append("Evidence coverage is discounted because fewer than two independent groups are linked.")
        if overlap:
            reasons.append("Linked evidence includes unresolved conflicting topics.")
        if not linked:
            reasons.append("No linked evidence supports this option.")
        return OptionAssessment(option.option_id, option.role, score, coverage, expected_value, overlap, tuple(reasons))

    @staticmethod
    def _holistic_review(request: DecisionRequest) -> tuple[str, ...]:
        return (
            "System dependencies: " + ("; ".join(request.system_factors) if request.system_factors else "not supplied; review required"),
            "Stakeholder impacts: " + ("; ".join(request.stakeholder_impacts) if request.stakeholder_impacts else "not supplied; review required"),
            "Time horizons: " + ", ".join(request.time_horizons),
            "Assumptions: " + ("; ".join(request.assumptions) if request.assumptions else "none declared"),
            "Second-order effects, reversibility and resilience must be reviewed before approval.",
        )

    def _hold_for_evidence(self, request: DecisionRequest, quality_score: float, sufficiency_score: float,
                           independent_count: int, conflicts: tuple[str, ...],
                           assessments: tuple[OptionAssessment, ...]) -> DecisionResult:
        return DecisionResult(
            status="HOLD_FOR_EVIDENCE",
            evidence_quality_score=quality_score,
            evidence_sufficiency_score=sufficiency_score,
            independent_source_count=independent_count,
            conflict_topics=conflicts,
            assessments=assessments,
            allocations=(),
            reserve_allocation=1.0,
            expected_gross_downside=0.0,
            expected_net_downside_after_hedge=0.0,
            human_approval_required=True,
            confidence_type="evidence_sufficiency_heuristic_not_probability",
            analysis_summary=(
                "Evidence sufficiency is below the configured threshold.",
                "No strategic allocation is recommended until independent evidence is strengthened.",
            ),
            holistic_review=self._holistic_review(request),
            caveats=(
                "All resources remain in reserve in HOLD_FOR_EVIDENCE status.",
                "A model-generated narrative cannot replace missing independent evidence.",
                "Human review is mandatory before any subsequent action.",
            ),
        )

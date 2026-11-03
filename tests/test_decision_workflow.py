from datetime import UTC, datetime, timedelta
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from ugai_decision import DecisionEngine, EvidenceItem, StrategicOption
from ugai_decision.mcp_source import MCPToolEvidenceSource, MCPToolQuery
from ugai_decision.workflow import (
    ApprovalDenied,
    ApprovalReceipt,
    DecisionAuditEvent,
    DecisionAuditUnavailable,
    DecisionWorkflow,
    EvidenceCollectionFailed,
)


def evidence(evidence_id: str, source_id: str, origin: str) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        topic="market_demand",
        position="positive",
        source_id=source_id,
        independence_group=origin,
        source_reliability=0.95,
        evidence_quality=0.95,
        relevance=0.95,
        freshness=0.95,
        verified=True,
        provenance_uri=f"https://evidence.example/{evidence_id}",
    )


class FakeSource:
    def __init__(self, source_id: str, records: Sequence[EvidenceItem], error: Exception | None = None):
        self.source_id = source_id
        self.records = tuple(records)
        self.error = error
        self.calls = 0

    async def collect(self, question: str, actor_id: str) -> Sequence[EvidenceItem]:
        self.calls += 1
        assert question
        assert actor_id == "trusted-user"
        if self.error is not None:
            raise self.error
        return self.records


class FakeAudit:
    def __init__(self, fail_at: int | None = None):
        self.events: list[DecisionAuditEvent] = []
        self.fail_at = fail_at

    async def append(self, event: DecisionAuditEvent) -> None:
        if self.fail_at is not None and len(self.events) == self.fail_at:
            raise OSError("audit unavailable")
        self.events.append(event)


class FakeApprovalGateway:
    def __init__(self):
        self.requests: list[dict[str, Any]] = []

    async def create_request(
        self,
        *,
        decision_id: str,
        actor_id: str,
        decision_snapshot: Mapping[str, Any],
        execution_plan: Mapping[str, Any] | None,
        plan_digest: str | None,
        idempotency_key: str,
    ) -> str:
        self.requests.append({
            "decision_id": decision_id,
            "actor_id": actor_id,
            "decision": decision_snapshot,
            "plan": execution_plan,
            "plan_digest": plan_digest,
            "idempotency_key": idempotency_key,
        })
        return "approval-ref-001"


class FakeVerifier:
    def __init__(self, receipt: ApprovalReceipt | None):
        self.receipt = receipt
        self.calls: list[dict[str, str]] = []

    async def verify(
        self, *, approval_reference: str, decision_id: str, actor_id: str, plan_digest: str
    ) -> ApprovalReceipt | None:
        self.calls.append({
            "approval_reference": approval_reference,
            "decision_id": decision_id,
            "actor_id": actor_id,
            "plan_digest": plan_digest,
        })
        return self.receipt


class FakeExecutor:
    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    async def execute(
        self, *, plan: Mapping[str, Any], actor_id: str, idempotency_key: str
    ) -> Mapping[str, Any]:
        self.calls.append({
            "plan": dict(plan),
            "actor_id": actor_id,
            "idempotency_key": idempotency_key,
        })
        return {"execution_id": "exec-001", "status": "accepted"}


def options() -> tuple[StrategicOption, ...]:
    linked = ("e1", "e2", "e3")
    return (
        StrategicOption(
            option_id="hedge",
            name="Diversify suppliers",
            role="hedge",
            evidence_ids=linked,
            risk_mitigation=0.9,
            strategic_fit=0.9,
            reversibility=0.8,
            cost=0.2,
            max_allocation=0.25,
        ),
        StrategicOption(
            option_id="bet",
            name="Enter market",
            role="bet",
            evidence_ids=linked,
            expected_upside=0.9,
            probability_success=0.8,
            downside_loss=0.3,
            strategic_fit=0.9,
            reversibility=0.8,
            cost=0.2,
            max_allocation=0.25,
        ),
    )


def make_workflow(
    sources: Sequence[FakeSource],
    *,
    audit: FakeAudit | None = None,
    approval: FakeApprovalGateway | None = None,
) -> tuple[DecisionWorkflow, FakeAudit, FakeApprovalGateway]:
    audit_sink = audit or FakeAudit()
    approval_gateway = approval or FakeApprovalGateway()
    workflow = DecisionWorkflow(
        sources=sources,
        audit_sink=audit_sink,
        approval_gateway=approval_gateway,
        plan_builder=lambda result: {
            "allocations": [
                {"option_id": item.option_id, "fraction": item.allocation}
                for item in result.allocations
            ],
            "decision_status": result.status,
        },
        engine=DecisionEngine(),
        source_timeout_seconds=2,
        max_concurrency=2,
    )
    return workflow, audit_sink, approval_gateway


@pytest.mark.asyncio
async def test_three_independent_mcp_sources_flow_to_approval_request() -> None:
    sources = [
        FakeSource("mcp-a", (evidence("e1", "mcp-a", "origin-a"),)),
        FakeSource("mcp-b", (evidence("e2", "mcp-b", "origin-b"),)),
        FakeSource("mcp-c", (evidence("e3", "mcp-c", "origin-c"),)),
    ]
    workflow, audit, approval = make_workflow(sources)

    result = await workflow.evaluate(
        question="Should we expand?",
        options=options(),
        actor_id="trusted-user",
        system_factors=("supplier concentration",),
        stakeholder_impacts=("employees", "customers"),
        assumptions=("market forecast is preliminary",),
    )

    assert result.decision.status == "RECOMMENDATION_READY"
    assert result.decision.human_approval_required is True
    assert result.approval_reference == "approval-ref-001"
    assert result.execution_plan is not None
    assert result.plan_digest is not None
    assert approval.requests[0]["plan_digest"] == result.plan_digest
    assert approval.requests[0]["idempotency_key"] == result.decision_id
    assert next(event.stage for event in audit.events) == "workflow_started"
    assert "decision_evaluated" in [event.stage for event in audit.events]
    assert [source.calls for source in sources] == [1, 1, 1]


@pytest.mark.asyncio
async def test_one_failed_source_rejects_all_partial_evidence() -> None:
    sources = [
        FakeSource("mcp-a", (evidence("e1", "mcp-a", "origin-a"),)),
        FakeSource("mcp-b", (evidence("e2", "mcp-b", "origin-b"),), RuntimeError("offline")),
        FakeSource("mcp-c", (evidence("e3", "mcp-c", "origin-c"),)),
    ]
    workflow, _, approval = make_workflow(sources)

    with pytest.raises(EvidenceCollectionFailed) as error:
        await workflow.evaluate(
            question="Should we expand?", options=options(), actor_id="trusted-user"
        )

    assert error.value.failed_sources == ("mcp-b",)
    assert approval.requests == []


@pytest.mark.asyncio
async def test_dependent_mcp_copies_do_not_satisfy_independent_evidence_gate() -> None:
    sources = [
        FakeSource("mcp-a", (evidence("e1", "mcp-a", "same-origin"),)),
        FakeSource("mcp-b", (evidence("e2", "mcp-b", "same-origin"),)),
        FakeSource("mcp-c", (evidence("e3", "mcp-c", "same-origin"),)),
    ]
    workflow, _, approval = make_workflow(sources)

    result = await workflow.evaluate(
        question="Should we expand?", options=options(), actor_id="trusted-user"
    )

    assert result.decision.status == "HOLD_FOR_EVIDENCE"
    assert result.decision.reserve_allocation == 1.0
    assert result.execution_plan is None
    assert approval.requests[0]["plan"] is None


@pytest.mark.asyncio
async def test_initial_audit_failure_blocks_mcp_collection() -> None:
    source = FakeSource("mcp-a", (evidence("e1", "mcp-a", "origin-a"),))
    audit = FakeAudit(fail_at=0)
    workflow, _, approval = make_workflow([source], audit=audit)

    with pytest.raises(DecisionAuditUnavailable) as error:
        await workflow.evaluate(
            question="Should we expand?", options=options(), actor_id="trusted-user"
        )

    assert error.value.execution_may_have_completed is False
    assert source.calls == 0
    assert approval.requests == []


@pytest.mark.asyncio
async def test_verified_approval_is_required_before_executor_runs() -> None:
    sources = [
        FakeSource("mcp-a", (evidence("e1", "mcp-a", "origin-a"),)),
        FakeSource("mcp-b", (evidence("e2", "mcp-b", "origin-b"),)),
        FakeSource("mcp-c", (evidence("e3", "mcp-c", "origin-c"),)),
    ]
    workflow, _, _ = make_workflow(sources)
    result = await workflow.evaluate(
        question="Should we expand?", options=options(), actor_id="trusted-user"
    )
    assert result.plan_digest is not None

    receipt = ApprovalReceipt(
        approval_reference=result.approval_reference,
        decision_id=result.decision_id,
        actor_id="trusted-user",
        plan_digest=result.plan_digest,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    verifier = FakeVerifier(receipt)
    executor = FakeExecutor()

    execution = await workflow.execute_approved(
        workflow_result=result,
        actor_id="trusted-user",
        approval_reference=result.approval_reference,
        idempotency_key="decision-exec-0001",
        verifier=verifier,
        executor=executor,
    )

    assert execution.receipt["status"] == "accepted"
    assert len(executor.calls) == 1
    assert executor.calls[0]["idempotency_key"] == "decision-exec-0001"


@pytest.mark.asyncio
async def test_invalid_approval_blocks_executor() -> None:
    sources = [
        FakeSource("mcp-a", (evidence("e1", "mcp-a", "origin-a"),)),
        FakeSource("mcp-b", (evidence("e2", "mcp-b", "origin-b"),)),
        FakeSource("mcp-c", (evidence("e3", "mcp-c", "origin-c"),)),
    ]
    workflow, _, _ = make_workflow(sources)
    result = await workflow.evaluate(
        question="Should we expand?", options=options(), actor_id="trusted-user"
    )
    verifier = FakeVerifier(None)
    executor = FakeExecutor()

    with pytest.raises(ApprovalDenied):
        await workflow.execute_approved(
            workflow_result=result,
            actor_id="trusted-user",
            approval_reference=result.approval_reference,
            idempotency_key="decision-exec-0002",
            verifier=verifier,
            executor=executor,
        )

    assert executor.calls == []


@pytest.mark.asyncio
async def test_plan_mutation_after_approval_request_is_rejected() -> None:
    sources = [
        FakeSource("mcp-a", (evidence("e1", "mcp-a", "origin-a"),)),
        FakeSource("mcp-b", (evidence("e2", "mcp-b", "origin-b"),)),
        FakeSource("mcp-c", (evidence("e3", "mcp-c", "origin-c"),)),
    ]
    workflow, _, _ = make_workflow(sources)
    result = await workflow.evaluate(
        question="Should we expand?", options=options(), actor_id="trusted-user"
    )
    assert result.execution_plan is not None
    result.execution_plan["tampered"] = True
    receipt = ApprovalReceipt(
        approval_reference=result.approval_reference,
        decision_id=result.decision_id,
        actor_id="trusted-user",
        plan_digest=result.plan_digest or "",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    executor = FakeExecutor()

    with pytest.raises(ApprovalDenied, match="changed"):
        await workflow.execute_approved(
            workflow_result=result,
            actor_id="trusted-user",
            approval_reference=result.approval_reference,
            idempotency_key="decision-exec-0003",
            verifier=FakeVerifier(receipt),
            executor=executor,
        )

    assert executor.calls == []


class FakeMCPProvider:
    def __init__(self):
        self.executed: list[tuple[str, Mapping[str, Any]]] = []

    async def discover(self) -> list[dict[str, Any]]:
        return [{"name": "search_records"}, {"name": "get_metrics"}]

    async def execute(self, tool_name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        self.executed.append((tool_name, dict(arguments)))
        return {"items": [{"id": "record-1"}]}


@pytest.mark.asyncio
async def test_mcp_evidence_source_uses_only_configured_discovered_tools() -> None:
    provider = FakeMCPProvider()
    source = MCPToolEvidenceSource(
        source_id="mcp-search",
        bound_actor_id="trusted-user",
        provider=provider,
        queries=(
            MCPToolQuery("search_records", lambda question: {"query": question}),
        ),
        extractor=lambda tool, response: (
            evidence("e1", "mcp-search", "primary-origin"),
        ),
    )

    records = await source.collect("market outlook", "trusted-user")

    assert records[0].source_id == "mcp-search"
    assert provider.executed == [("search_records", {"query": "market outlook"})]


@pytest.mark.asyncio
async def test_mcp_evidence_source_rejects_actor_mismatch() -> None:
    provider = FakeMCPProvider()
    source = MCPToolEvidenceSource(
        source_id="mcp-search",
        bound_actor_id="user-one",
        provider=provider,
        queries=(MCPToolQuery("search_records", lambda question: {"query": question}),),
        extractor=lambda tool, response: (),
    )

    with pytest.raises(PermissionError):
        await source.collect("market outlook", "user-two")

    assert provider.executed == []

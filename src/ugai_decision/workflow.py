"""Fail-closed multi-source decision orchestration and approval-gated execution."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from .engine import DecisionEngine
from .models import DecisionRequest, DecisionResult, EvidenceItem, StrategicOption


class EvidenceSource(Protocol):
    source_id: str

    async def collect(self, question: str, actor_id: str) -> Sequence[EvidenceItem]:
        """Collect normalized, attributable evidence for a trusted actor."""


@dataclass(frozen=True, slots=True)
class DecisionAuditEvent:
    event_id: str
    workflow_id: str
    decision_id: str
    actor_id: str
    stage: str
    outcome: str
    occurred_at: str
    details: tuple[tuple[str, str], ...]


class DecisionAuditSink(Protocol):
    async def append(self, event: DecisionAuditEvent) -> None:
        """Durably append a redacted event or raise an exception."""


@dataclass(frozen=True, slots=True)
class EvidenceManifestRecord:
    """Human-reviewable evidence metadata without copying untrusted document text."""

    evidence_id: str
    topic: str
    position: str
    source_id: str
    independence_group: str
    source_reliability: float
    evidence_quality: float
    relevance: float
    freshness: float
    verified: bool
    provenance_uri: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "topic": self.topic,
            "position": self.position,
            "source_id": self.source_id,
            "independence_group": self.independence_group,
            "source_reliability": self.source_reliability,
            "evidence_quality": self.evidence_quality,
            "relevance": self.relevance,
            "freshness": self.freshness,
            "verified": self.verified,
            "provenance_uri": self.provenance_uri,
        }


class ApprovalGateway(Protocol):
    async def create_request(
        self,
        *,
        decision_id: str,
        actor_id: str,
        decision_snapshot: Mapping[str, Any],
        evidence_manifest: Sequence[EvidenceManifestRecord],
        evidence_digest: str,
        source_ids: Sequence[str],
        execution_plan: Mapping[str, Any] | None,
        plan_digest: str | None,
        idempotency_key: str,
    ) -> str:
        """Persist a human approval/review request idempotently."""


@dataclass(frozen=True, slots=True)
class ApprovalReceipt:
    approval_reference: str
    decision_id: str
    actor_id: str
    plan_digest: str
    expires_at: datetime


class ApprovalVerifier(Protocol):
    async def verify(
        self,
        *,
        approval_reference: str,
        decision_id: str,
        actor_id: str,
        plan_digest: str,
    ) -> ApprovalReceipt | None:
        """Verify a trusted, scoped, unexpired human approval receipt."""


class ExecutionPort(Protocol):
    async def execute(
        self,
        *,
        plan: Mapping[str, Any],
        actor_id: str,
        idempotency_key: str,
    ) -> Mapping[str, Any]:
        """Execute an approved plan idempotently and return a redacted receipt."""


PlanBuilder = Callable[[DecisionResult], Mapping[str, Any]]


class DecisionWorkflowError(RuntimeError):
    """Base class for decision orchestration failures."""


class DecisionAuditUnavailable(DecisionWorkflowError):
    def __init__(
        self,
        message: str,
        *,
        decision_id: str,
        execution_may_have_completed: bool = False,
    ) -> None:
        super().__init__(message)
        self.decision_id = decision_id
        self.execution_may_have_completed = execution_may_have_completed


class EvidenceCollectionFailed(DecisionWorkflowError):
    def __init__(self, decision_id: str, failed_sources: Sequence[str]) -> None:
        super().__init__("One or more required evidence sources failed; partial evidence was rejected")
        self.decision_id = decision_id
        self.failed_sources = tuple(failed_sources)


class ApprovalDenied(DecisionWorkflowError):
    """Raised when approval is absent, invalid, expired, or out of scope."""


class WorkflowConfigurationError(DecisionWorkflowError):
    """Raised for invalid workflow wiring or policy settings."""


@dataclass(frozen=True, slots=True)
class DecisionWorkflowResult:
    workflow_id: str
    decision_id: str
    actor_id: str
    decision: DecisionResult
    approval_reference: str
    evidence_manifest: tuple[EvidenceManifestRecord, ...]
    evidence_digest: str
    source_ids: tuple[str, ...]
    execution_plan: Mapping[str, Any] | None
    plan_digest: str | None


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    decision_id: str
    idempotency_key: str
    receipt: Mapping[str, Any]


def _canonical_plan(plan: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    if not isinstance(plan, Mapping):
        raise TypeError("execution plan must be a mapping")
    try:
        normalized = json.loads(json.dumps(plan, sort_keys=True, separators=(",", ":"), allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError("execution plan must contain only finite JSON-compatible values") from exc
    if not isinstance(normalized, dict):
        raise TypeError("execution plan must serialize to a JSON object")
    digest = hashlib.sha256(
        json.dumps(normalized, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    return normalized, digest


class DecisionWorkflow:
    """Collect evidence, evaluate it and request approval through injected ports.

    All evidence sources are mandatory. One failed source rejects the complete
    collection by default; silent partial-source decisions are not permitted.
    """

    def __init__(
        self,
        *,
        sources: Sequence[EvidenceSource],
        audit_sink: DecisionAuditSink,
        approval_gateway: ApprovalGateway,
        plan_builder: PlanBuilder,
        engine: DecisionEngine | None = None,
        source_timeout_seconds: float = 30.0,
        max_concurrency: int = 4,
    ) -> None:
        if not sources:
            raise WorkflowConfigurationError("at least one evidence source is required")
        source_ids = [source.source_id for source in sources]
        if any(not isinstance(value, str) or not value.strip() for value in source_ids):
            raise WorkflowConfigurationError("every evidence source needs a stable source_id")
        if len(set(source_ids)) != len(source_ids):
            raise WorkflowConfigurationError("evidence source_id values must be unique")
        if source_timeout_seconds <= 0:
            raise WorkflowConfigurationError("source_timeout_seconds must be positive")
        if max_concurrency < 1:
            raise WorkflowConfigurationError("max_concurrency must be at least 1")
        if not callable(plan_builder):
            raise WorkflowConfigurationError("plan_builder must be trusted application code")

        self._sources = tuple(sources)
        self._audit = audit_sink
        self._approval = approval_gateway
        self._plan_builder = plan_builder
        self._engine = engine or DecisionEngine()
        self._timeout = source_timeout_seconds
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def evaluate(
        self,
        *,
        question: str,
        options: Sequence[StrategicOption],
        actor_id: str,
        system_factors: Sequence[str] = (),
        stakeholder_impacts: Sequence[str] = (),
        time_horizons: Sequence[str] = ("short_term", "long_term"),
        assumptions: Sequence[str] = (),
        risk_tolerance: str = "balanced",
        evidence_threshold: float = 0.50,
        reserve_floor: float = 0.15,
        hedge_target: float = 0.20,
        max_bet_allocation: float = 0.25,
        risk_budget: float = 0.25,
    ) -> DecisionWorkflowResult:
        if not isinstance(actor_id, str) or not actor_id.strip():
            raise PermissionError("A trusted authenticated actor_id is required")
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question must be a non-empty string")

        workflow_id = uuid4().hex
        decision_id = uuid4().hex
        await self._write_audit(
            workflow_id, decision_id, actor_id, "workflow_started", "started",
            (("source_count", str(len(self._sources))),),
            may_have_completed=False,
        )

        async def collect(source: EvidenceSource) -> tuple[str, tuple[EvidenceItem, ...]]:
            async with self._semaphore:
                result = await asyncio.wait_for(
                    source.collect(question, actor_id),
                    timeout=self._timeout,
                )
            if not isinstance(result, Sequence) or isinstance(result, (str, bytes)):
                raise TypeError("evidence source must return a sequence")
            records = tuple(result)
            if not all(isinstance(item, EvidenceItem) for item in records):
                raise TypeError("evidence source returned an invalid evidence record")
            if any(item.source_id != source.source_id for item in records):
                raise ValueError("evidence source returned a record owned by another source")
            if any(not item.provenance_uri or not item.provenance_uri.strip() for item in records):
                raise ValueError("every evidence record must include a stable provenance locator")
            return source.source_id, records

        collected = await asyncio.gather(
            *(collect(source) for source in self._sources),
            return_exceptions=True,
        )
        failures: list[str] = []
        evidence: list[EvidenceItem] = []
        successful_sources: list[tuple[str, tuple[EvidenceItem, ...]]] = []
        for source, value in zip(self._sources, collected, strict=True):
            if isinstance(value, BaseException):
                failures.append(source.source_id)
                await self._write_audit(
                    workflow_id, decision_id, actor_id, "evidence_source_failed", "failed",
                    (("source_id", source.source_id), ("error_type", type(value).__name__)),
                    may_have_completed=True,
                )
            else:
                successful_sources.append(value)
                evidence.extend(value[1])

        if failures:
            await self._write_audit(
                workflow_id, decision_id, actor_id, "evidence_collection_rejected", "failed",
                (("failed_source_count", str(len(failures))),),
                may_have_completed=True,
            )
            raise EvidenceCollectionFailed(decision_id, failures)

        evidence_ids = [item.evidence_id for item in evidence]
        if len(set(evidence_ids)) != len(evidence_ids):
            await self._write_audit(
                workflow_id, decision_id, actor_id, "evidence_collection_rejected", "failed",
                (("reason", "duplicate_evidence_ids"),),
                may_have_completed=True,
            )
            raise DecisionWorkflowError("Evidence IDs must be unique across all MCP sources")

        for source_id, records in successful_sources:
            await self._write_audit(
                workflow_id, decision_id, actor_id, "evidence_source_collected", "succeeded",
                (("source_id", source_id), ("record_count", str(len(records)))),
                may_have_completed=True,
            )

        request = DecisionRequest(
            question=question,
            evidence=tuple(evidence),
            options=tuple(options),
            system_factors=tuple(system_factors),
            stakeholder_impacts=tuple(stakeholder_impacts),
            time_horizons=tuple(time_horizons),
            assumptions=tuple(assumptions),
            risk_tolerance=risk_tolerance,
            evidence_threshold=evidence_threshold,
            reserve_floor=reserve_floor,
            hedge_target=hedge_target,
            max_bet_allocation=max_bet_allocation,
            risk_budget=risk_budget,
        )
        result = self._engine.evaluate(request)
        evidence_manifest = self._evidence_manifest(evidence)
        evidence_digest = self._evidence_digest(evidence_manifest)
        source_ids = tuple(sorted(source_id for source_id, _ in successful_sources))
        await self._write_audit(
            workflow_id, decision_id, actor_id, "decision_evaluated", result.status,
            (
                ("evidence_count", str(len(evidence))),
                ("evidence_sha256", evidence_digest),
                ("independent_source_count", str(result.independent_source_count)),
                ("conflict_count", str(len(result.conflict_topics))),
            ),
            may_have_completed=True,
        )

        execution_plan: dict[str, Any] | None = None
        plan_digest: str | None = None
        if result.status == "RECOMMENDATION_READY":
            raw_plan = self._plan_builder(result)
            execution_plan, plan_digest = _canonical_plan(raw_plan)

        await self._write_audit(
            workflow_id, decision_id, actor_id, "approval_request_started", "started",
            (("decision_status", result.status), ("plan_digest", plan_digest or "none")),
            may_have_completed=True,
        )
        try:
            approval_reference = await self._approval.create_request(
                decision_id=decision_id,
                actor_id=actor_id,
                decision_snapshot=result.to_dict(),
                evidence_manifest=evidence_manifest,
                evidence_digest=evidence_digest,
                source_ids=source_ids,
                execution_plan=execution_plan,
                plan_digest=plan_digest,
                idempotency_key=decision_id,
            )
        except Exception as exc:
            await self._write_audit(
                workflow_id, decision_id, actor_id, "approval_request_failed", "failed",
                (("error_type", type(exc).__name__),),
                may_have_completed=True,
            )
            raise DecisionWorkflowError("Human approval request could not be confirmed") from exc
        if not isinstance(approval_reference, str) or not approval_reference.strip():
            raise DecisionWorkflowError("Approval gateway returned an invalid reference")

        await self._write_audit(
            workflow_id, decision_id, actor_id, "approval_requested", "pending",
            (("approval_reference", approval_reference), ("decision_status", result.status)),
            may_have_completed=True,
        )
        return DecisionWorkflowResult(
            workflow_id=workflow_id,
            decision_id=decision_id,
            actor_id=actor_id,
            decision=result,
            approval_reference=approval_reference,
            evidence_manifest=evidence_manifest,
            evidence_digest=evidence_digest,
            source_ids=source_ids,
            execution_plan=execution_plan,
            plan_digest=plan_digest,
        )

    async def execute_approved(
        self,
        *,
        workflow_result: DecisionWorkflowResult,
        actor_id: str,
        approval_reference: str,
        idempotency_key: str,
        verifier: ApprovalVerifier,
        executor: ExecutionPort,
    ) -> ExecutionResult:
        """Execute only the exact plan bound to a verified, unexpired approval.

        The executor must enforce idempotency and independently authorize the
        actor. A timeout or post-execution audit failure requires reconciliation
        by idempotency_key; callers must not blindly retry.
        """
        if actor_id != workflow_result.actor_id or not actor_id.strip():
            raise PermissionError("Execution actor does not match the decision actor")
        if workflow_result.decision.status != "RECOMMENDATION_READY":
            raise ApprovalDenied("Only a recommendation-ready decision can be executed")
        if workflow_result.execution_plan is None or workflow_result.plan_digest is None:
            raise ApprovalDenied("No approved execution plan exists for this decision")
        if approval_reference != workflow_result.approval_reference:
            raise ApprovalDenied("Approval reference does not match the decision")
        if not isinstance(idempotency_key, str) or len(idempotency_key.strip()) < 8:
            raise ValueError("A stable idempotency key of at least 8 characters is required")

        plan, calculated_digest = _canonical_plan(workflow_result.execution_plan)
        if calculated_digest != workflow_result.plan_digest:
            raise ApprovalDenied("Execution plan changed after the approval request was created")

        receipt = await verifier.verify(
            approval_reference=approval_reference,
            decision_id=workflow_result.decision_id,
            actor_id=actor_id,
            plan_digest=calculated_digest,
        )
        if receipt is None:
            raise ApprovalDenied("No valid human approval receipt was found")
        now = datetime.now(UTC)
        if (
            receipt.approval_reference != approval_reference
            or receipt.decision_id != workflow_result.decision_id
            or receipt.actor_id != actor_id
            or receipt.plan_digest != calculated_digest
            or not isinstance(receipt.expires_at, datetime)
            or receipt.expires_at.tzinfo is None
            or receipt.expires_at <= now
        ):
            raise ApprovalDenied("Human approval receipt is invalid, expired or out of scope")

        await self._write_audit(
            workflow_result.workflow_id, workflow_result.decision_id, actor_id,
            "execution_authorized", "approved",
            (("plan_digest", calculated_digest), ("idempotency_key", idempotency_key)),
            may_have_completed=False,
        )
        try:
            execution_receipt = await executor.execute(
                plan=plan,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            await self._write_audit(
                workflow_result.workflow_id, workflow_result.decision_id, actor_id,
                "execution_outcome_unknown", "unknown",
                (("error_type", type(exc).__name__), ("idempotency_key", idempotency_key)),
                may_have_completed=True,
            )
            raise DecisionWorkflowError(
                "Execution outcome is unknown; reconcile using the idempotency key before retrying"
            ) from exc
        if not isinstance(execution_receipt, Mapping):
            raise DecisionWorkflowError("Executor returned an invalid execution receipt")

        await self._write_audit(
            workflow_result.workflow_id, workflow_result.decision_id, actor_id,
            "execution_completed", "succeeded",
            (("idempotency_key", idempotency_key),),
            may_have_completed=True,
        )
        return ExecutionResult(
            decision_id=workflow_result.decision_id,
            idempotency_key=idempotency_key,
            receipt=dict(execution_receipt),
        )

    async def _write_audit(
        self,
        workflow_id: str,
        decision_id: str,
        actor_id: str,
        stage: str,
        outcome: str,
        details: tuple[tuple[str, str], ...],
        *,
        may_have_completed: bool,
    ) -> None:
        event = DecisionAuditEvent(
            event_id=uuid4().hex,
            workflow_id=workflow_id,
            decision_id=decision_id,
            actor_id=actor_id,
            stage=stage,
            outcome=outcome,
            occurred_at=datetime.now(UTC).isoformat(),
            details=details,
        )
        try:
            await self._audit.append(event)
        except Exception as exc:
            raise DecisionAuditUnavailable(
                f"Durable decision audit failed at stage {stage}",
                decision_id=decision_id,
                execution_may_have_completed=may_have_completed,
            ) from exc

    @staticmethod
    def _evidence_manifest(
        evidence: Sequence[EvidenceItem],
    ) -> tuple[EvidenceManifestRecord, ...]:
        return tuple(
            EvidenceManifestRecord(
                evidence_id=item.evidence_id,
                topic=item.topic,
                position=item.position,
                source_id=item.source_id,
                independence_group=item.independence_group,
                source_reliability=item.source_reliability,
                evidence_quality=item.evidence_quality,
                relevance=item.relevance,
                freshness=item.freshness,
                verified=item.verified,
                provenance_uri=item.provenance_uri or "",
            )
            for item in sorted(evidence, key=lambda value: value.evidence_id)
        )

    @staticmethod
    def _evidence_digest(manifest: Sequence[EvidenceManifestRecord]) -> str:
        records = [item.to_dict() for item in manifest]
        serialized = json.dumps(records, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

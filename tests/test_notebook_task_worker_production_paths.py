from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from app.config import settings
from app.notebook_task_worker import (
    NotebookReasoningTaskHandler,
    NotebookTaskInputInvalid,
    reconcile_outcome_unknown_once,
)
from app.task_api import TaskSubmission
from app.reasoning.routing import NoEligibleModelRoute
from ugai_workflow.payload_cipher import TaskPayloadCipher
from ugai_workflow.state_machine import TaskState
from ugai_workflow.worker import ExternalOutcomeUnknown


class Store:
    def __init__(self, *, payload=None, result=None, tasks=None):
        self.payload = payload
        self.result = result
        self.tasks = list(tasks or [])
        self.put_calls = []
        self.transition_calls = []

    async def get_encrypted_payload(self, **_kwargs):
        return self.payload

    async def get_encrypted_result(self, **_kwargs):
        return self.result

    async def put_encrypted_result(self, **kwargs):
        self.put_calls.append(kwargs)
        self.result = (kwargs["key_id"], kwargs["ciphertext"], kwargs["payload_sha256"])
        return kwargs["payload_sha256"]

    async def list_outcome_unknown(self, **_kwargs):
        return self.tasks

    async def transition(self, **kwargs):
        self.transition_calls.append(kwargs)
        return SimpleNamespace(state=kwargs["target"])


def cipher():
    return TaskPayloadCipher(Fernet.generate_key().decode("ascii"), key_id="worker-test-v1")


def task(state=TaskState.EXECUTING, **overrides):
    value = {
        "task_id": uuid4(),
        "tenant_id": "tenant-a",
        "actor_id": "actor-a",
        "project_id": "project-a",
        "task_type": "notebook_task",
        "state": state,
        "version": 3,
    }
    value.update(overrides)
    return SimpleNamespace(**value)


def submission(**overrides):
    value = {
        "project_id": "project-a",
        "workspace_id": uuid4(),
        "intent": "Analyze the supplied notebook context",
        "context": "Use only the supplied context.",
        "artifacts": (),
        "requested_capabilities": ("reasoning:read",),
    }
    value.update(overrides)
    return TaskSubmission(**value)


def result_value(value_task, **overrides):
    value = {
        "task_id": str(value_task.task_id),
        "project_id": value_task.project_id,
        "candidate_answer": "A bounded candidate answer",
        "independent_review": "An independent critique",
        "verification_status": "needs_human_review",
        "human_review_required": True,
        "tool_execution_performed": False,
    }
    value.update(overrides)
    return value


def encrypted_payload(value_cipher, value_submission):
    encrypted, digest = value_cipher.encrypt(value_submission.model_dump(mode="json"))
    return ("worker-test-v1", encrypted, digest)


@pytest.mark.asyncio
async def test_payload_rejects_missing_corrupt_and_wrong_scope_inputs():
    value_cipher = cipher()
    value_task = task()
    handler = NotebookReasoningTaskHandler(store=Store(), cipher=value_cipher)
    with pytest.raises(NotebookTaskInputInvalid, match="encrypted_input_missing"):
        await handler._payload(value_task)

    store = Store(payload=("worker-test-v1", b"tampered", "a" * 64))
    handler = NotebookReasoningTaskHandler(store=store, cipher=value_cipher)
    with pytest.raises(NotebookTaskInputInvalid, match="integrity_or_schema_invalid"):
        await handler._payload(value_task)

    other_project = submission(project_id="project-b")
    store.payload = encrypted_payload(value_cipher, other_project)
    with pytest.raises(NotebookTaskInputInvalid, match="project_scope_mismatch"):
        await handler._payload(value_task)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("capabilities", "artifacts", "expected"),
    [
        (("reasoning:read", "mcp:write"), (), "capability_not_allowed"),
        (("reasoning:read",), ({"artifact_id": "a", "sha256": "a" * 64, "media_type": "text/plain"},), "artifact_fetch_not_enabled"),
    ],
)
async def test_payload_rejects_unapproved_capabilities_and_artifacts(capabilities, artifacts, expected):
    value_cipher = cipher()
    value_submission = submission(
        requested_capabilities=capabilities,
        artifacts=artifacts,
    )
    store = Store(payload=encrypted_payload(value_cipher, value_submission))
    handler = NotebookReasoningTaskHandler(store=store, cipher=value_cipher)
    with pytest.raises(NotebookTaskInputInvalid, match=expected):
        await handler._payload(task())


def test_requirements_enforce_permitted_regions_and_bounded_token_budget(monkeypatch):
    monkeypatch.setattr(settings, "reasoning_permitted_data_regions", "eu-west-1, us-east-1")
    value = submission(intent="x" * 80, context="y" * 40)
    requirements = NotebookReasoningTaskHandler._requirements(value)
    assert requirements.permitted_data_regions == {"eu-west-1", "us-east-1"}
    assert requirements.estimated_input_tokens == 30
    assert requirements.max_output_tokens == 2048

    monkeypatch.setattr(settings, "reasoning_permitted_data_regions", " , ")
    with pytest.raises(NoEligibleModelRoute, match="No permitted reasoning data region"):
        NotebookReasoningTaskHandler._requirements(value)


@pytest.mark.asyncio
async def test_executor_requires_independent_evaluator_and_builds_stable_plan_digest(monkeypatch):
    from app import notebook_task_worker as worker_module

    value_submission = submission()
    route = SimpleNamespace(
        route_id="route-primary",
        provider="provider-a",
        model_id="model-a",
        model_revision="a" * 40,
    )
    evaluator = SimpleNamespace(
        route_id="route-evaluator",
        provider="provider-b",
        model_id="model-b",
        model_revision="b" * 40,
    )
    decision = SimpleNamespace(primary=route, fallback=None, independent_evaluator=None)
    monkeypatch.setattr(worker_module, "load_approved_text_routes", _async_value([]))
    monkeypatch.setattr(worker_module, "select_model_routes", lambda *_args: decision)
    monkeypatch.setattr(settings, "reasoning_permitted_data_regions", "us-east-1")
    handler = NotebookReasoningTaskHandler(store=Store(), cipher=cipher())
    with pytest.raises(NoEligibleModelRoute, match="independent evaluator"):
        await handler._executor(value_submission)

    decision.independent_evaluator = evaluator
    monkeypatch.setattr(worker_module, "load_approved_text_routes", _async_value([route, evaluator]))
    from app.providers import router as provider_router

    monkeypatch.setattr(
        provider_router.TextModelRouter,
        "from_settings",
        staticmethod(lambda: "router"),
    )
    captured = {}

    class FakeExecutor:
        def __init__(self, *, router, routes):
            captured["router"] = router
            captured["routes"] = routes

    monkeypatch.setattr(worker_module, "PolicyRoutedTextExecutor", FakeExecutor)
    executor, requirements, digest = await handler._executor(value_submission)
    assert isinstance(executor, FakeExecutor)
    assert captured == {"router": "router", "routes": [route, evaluator]}
    assert requirements.max_output_tokens == 2048
    assert len(digest) == 64


def _async_value(value):
    async def result(*_args, **_kwargs):
        return value
    return result


def test_result_payload_rejects_missing_evaluator_and_invalid_model_output():
    value_task = task()
    value_submission = submission()
    route = SimpleNamespace(
        route_id="route-1", provider="provider-a", model_id="model-a", model_revision="a" * 40
    )
    missing_evaluator = SimpleNamespace(
        decision=SimpleNamespace(independent_evaluator=None),
        independent_evaluation=None,
        completion=SimpleNamespace(final_content="answer"),
        execution_route=route,
        fallback_used=False,
    )
    with pytest.raises(ExternalOutcomeUnknown, match="independent_evaluator_result_missing"):
        NotebookReasoningTaskHandler._result_payload(
            task=value_task, submission=value_submission, policy_result=missing_evaluator
        )

    bad_candidate = SimpleNamespace(
        decision=SimpleNamespace(independent_evaluator=route),
        independent_evaluation=SimpleNamespace(final_content="critique"),
        completion=SimpleNamespace(final_content=" "),
        execution_route=route,
        fallback_used=False,
    )
    with pytest.raises(ExternalOutcomeUnknown, match="reasoning_result_invalid"):
        NotebookReasoningTaskHandler._result_payload(
            task=value_task, submission=value_submission, policy_result=bad_candidate
        )


def test_result_validation_rejects_scope_and_review_contract_drift():
    value_task = task()
    valid = result_value(value_task)
    NotebookReasoningTaskHandler._validate_result(value_task, valid)
    for invalid in (
        {**valid, "task_id": str(uuid4())},
        {**valid, "project_id": "project-b"},
        {**valid, "verification_status": "verified"},
        {**valid, "human_review_required": False},
        {**valid, "tool_execution_performed": True},
        {**valid, "candidate_answer": " "},
        {**valid, "independent_review": ""},
    ):
        with pytest.raises(ValueError, match="result_contract_invalid"):
            NotebookReasoningTaskHandler._validate_result(value_task, invalid)


@pytest.mark.asyncio
async def test_received_and_unsupported_task_states_are_explicit():
    handler = NotebookReasoningTaskHandler(store=Store(), cipher=cipher())
    received = await handler.handle(task(state=TaskState.RECEIVED))
    assert received.next_state is TaskState.OBSERVING
    unsupported = await handler.handle(task(state=TaskState.RECEIVED, task_type="other_task"))
    assert unsupported.next_state is TaskState.BLOCKED
    assert unsupported.error_code == "unsupported_task_type"
    unknown = await handler.handle(task(state=TaskState.AWAITING_APPROVAL))
    assert unknown.next_state is TaskState.BLOCKED
    assert unknown.error_code == "notebook_task_state_unsupported"


@pytest.mark.asyncio
async def test_planning_stage_preflights_and_blocks_unavailable_routes(monkeypatch):
    handler = NotebookReasoningTaskHandler(store=Store(), cipher=cipher())
    value_submission = submission()
    monkeypatch.setattr(handler, "_payload", _async_value(value_submission))
    monkeypatch.setattr(handler, "_executor", _async_value((object(), object(), "d" * 64)))
    ready = await handler.handle(task(state=TaskState.PLANNING))
    assert ready.next_state is TaskState.EXECUTING
    assert ready.plan_digest == "d" * 64

    async def unavailable(_submission):
        raise NoEligibleModelRoute("no safe route")

    monkeypatch.setattr(handler, "_executor", unavailable)
    blocked = await handler.handle(task(state=TaskState.PLANNING))
    assert blocked.next_state is TaskState.BLOCKED
    assert blocked.error_code == "reasoning_route_unavailable"


@pytest.mark.asyncio
async def test_executing_stage_recovers_existing_result_or_quarantines_corruption():
    value_cipher = cipher()
    value_task = task()
    encrypted, digest = value_cipher.encrypt(result_value(value_task))
    store = Store(result=("worker-test-v1", encrypted, digest))
    handler = NotebookReasoningTaskHandler(store=store, cipher=value_cipher)
    recovered = await handler.handle(value_task)
    assert recovered.next_state is TaskState.VERIFYING
    assert recovered.decision_digest == digest
    assert recovered.metadata["verification_status"] == "needs_human_review"

    store.result = ("worker-test-v1", b"corrupt", digest)
    with pytest.raises(ExternalOutcomeUnknown, match="persisted_notebook_result_integrity_failure"):
        await handler.handle(value_task)


@pytest.mark.asyncio
async def test_executing_stage_persists_policy_result_and_quarantines_uncertain_failures(monkeypatch):
    value_cipher = cipher()
    value_task = task()
    value_submission = submission()
    store = Store()
    handler = NotebookReasoningTaskHandler(store=store, cipher=value_cipher)
    executor = SimpleNamespace(execute=_async_value(SimpleNamespace()))
    monkeypatch.setattr(handler, "_payload", _async_value(value_submission))
    monkeypatch.setattr(handler, "_executor", _async_value((executor, object(), "c" * 64)))
    monkeypatch.setattr(
        NotebookReasoningTaskHandler,
        "_result_payload",
        staticmethod(lambda **_kwargs: result_value(value_task)),
    )

    persisted = await handler.handle(value_task)
    assert persisted.next_state is TaskState.VERIFYING
    assert len(store.put_calls) == 1
    assert store.put_calls[0]["payload_sha256"] == persisted.decision_digest

    async def provider_failure(**_kwargs):
        raise RuntimeError("provider timeout after submission")

    executor.execute = provider_failure
    store.result = None
    with pytest.raises(ExternalOutcomeUnknown, match="external_outcome_requires_reconciliation"):
        await handler.handle(value_task)


@pytest.mark.asyncio
async def test_verifying_stage_requires_a_valid_persisted_result():
    value_cipher = cipher()
    value_task = task(state=TaskState.VERIFYING)
    store = Store()
    handler = NotebookReasoningTaskHandler(store=store, cipher=value_cipher)
    missing = await handler.handle(value_task)
    assert missing.next_state is TaskState.BLOCKED
    assert missing.error_code == "notebook_result_missing"

    encrypted, digest = value_cipher.encrypt(result_value(value_task, tool_execution_performed=True))
    store.result = ("worker-test-v1", encrypted, digest)
    invalid = await handler.handle(value_task)
    assert invalid.next_state is TaskState.BLOCKED
    assert invalid.error_code == "notebook_result_integrity_failure"

    encrypted, digest = value_cipher.encrypt(result_value(value_task))
    store.result = ("worker-test-v1", encrypted, digest)
    valid = await handler.handle(value_task)
    assert valid.next_state is TaskState.SUCCEEDED
    assert valid.decision_digest == digest


@pytest.mark.asyncio
async def test_reconciliation_preserves_quarantine_for_corrupt_results_and_failed_transitions():
    value_cipher = cipher()
    first = task(state=TaskState.OUTCOME_UNKNOWN)
    second = task(state=TaskState.OUTCOME_UNKNOWN)
    valid_ciphertext, valid_digest = value_cipher.encrypt(result_value(second))
    corrupt = Store(
        result=("worker-test-v1", b"tampered", "a" * 64),
        tasks=[first],
    )
    assert await reconcile_outcome_unknown_once(
        store=corrupt, cipher=value_cipher, tenant_id="tenant-a"
    ) == 0
    assert corrupt.transition_calls == []

    failing_transition = Store(
        result=("worker-test-v1", valid_ciphertext, valid_digest),
        tasks=[second],
    )

    async def fail_transition(**_kwargs):
        raise RuntimeError("stale or unavailable")

    failing_transition.transition = fail_transition
    assert await reconcile_outcome_unknown_once(
        store=failing_transition, cipher=value_cipher, tenant_id="tenant-a"
    ) == 0

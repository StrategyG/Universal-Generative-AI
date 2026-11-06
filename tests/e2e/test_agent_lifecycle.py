from __future__ import annotations

import os
import time
from uuid import uuid4

import httpx
import pytest


@pytest.mark.e2e
def test_authenticated_user_task_reaches_verified_agent_result():
    """Exercise the real deployed API, worker, persistence and result path."""
    base_url = os.getenv("RUSA_E2E_BASE_URL", "").rstrip("/")
    bearer_token = os.getenv("RUSA_E2E_BEARER_TOKEN", "")
    project_id = os.getenv("RUSA_E2E_PROJECT_ID", "")
    if not all((base_url, bearer_token, project_id)):
        pytest.skip(
            "Set RUSA_E2E_BASE_URL, RUSA_E2E_BEARER_TOKEN and "
            "RUSA_E2E_PROJECT_ID to run the staging E2E gate"
        )

    timeout_seconds = int(os.getenv("RUSA_E2E_TIMEOUT_SECONDS", "300"))
    workspace_id = os.getenv("RUSA_E2E_WORKSPACE_ID") or str(uuid4())
    request_id = str(uuid4())
    correlation_id = str(uuid4())
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Idempotency-Key": f"e2e-{uuid4().hex}",
        "X-Request-ID": request_id,
        "X-Correlation-ID": correlation_id,
    }
    payload = {
        "project_id": project_id,
        "workspace_id": workspace_id,
        "intent": (
            "Return a concise summary of this instruction and a structured result. "
            "Do not call external tools, modify files, or perform external side effects."
        ),
        "context": "Production-readiness end-to-end validation.",
        "artifacts": [],
        "requested_capabilities": ["reasoning:read"],
    }

    expected_environment = os.getenv("RUSA_E2E_EXPECTED_ENVIRONMENT", "staging").strip().lower()
    with httpx.Client(
        base_url=base_url,
        headers={"Authorization": f"Bearer {bearer_token}"},
        timeout=httpx.Timeout(15.0, connect=5.0),
        follow_redirects=False,
    ) as client:
        health = client.get("/health")
        assert health.status_code == 200, (
            f"Staging health check failed with HTTP {health.status_code}"
        )
        health_body = health.json()
        assert str(health_body.get("environment", "")).lower() == expected_environment, (
            "E2E target environment mismatch; refusing to create a task outside "
            f"the expected {expected_environment!r} environment"
        )
        assert health_body.get("queue_backend") == "postgresql"
        assert health_body.get("queue_persistent") is True
        assert health_body.get("worker_scoped_credentials_enabled") is True

        submitted = client.post(
            "/api/v1/tasks",
            json=payload,
            headers={
                key: value
                for key, value in headers.items()
                if key != "Authorization"
            },
        )
        assert submitted.status_code == 202, (
            "Task submission must be accepted by the real staging API; "
            f"received HTTP {submitted.status_code}"
        )
        submission = submitted.json()
        task_id = submission["task_id"]
        assert submission["project_id"] == project_id
        assert submission["state"] in {
            "queued", "running", "awaiting_approval", "awaiting_clarification"
        }

        deadline = time.monotonic() + timeout_seconds
        latest_status = submission
        while time.monotonic() < deadline:
            status_response = client.get(f"/api/v1/tasks/{task_id}")
            assert status_response.status_code == 200, (
                f"Task status read failed with HTTP {status_response.status_code}"
            )
            latest_status = status_response.json()
            state = latest_status["state"]
            if state == "succeeded":
                break
            if state in {"failed", "cancelled", "blocked", "outcome_unknown"}:
                pytest.fail(
                    f"Real agent task entered terminal/non-success state: {state}; "
                    f"error_code={latest_status.get('error_code')}"
                )
            time.sleep(2)
        else:
            pytest.fail(
                f"Real agent task did not complete within {timeout_seconds}s; "
                f"last state={latest_status.get('state')}"
            )

        result_response = client.get(f"/api/v1/tasks/{task_id}/result")
        assert result_response.status_code == 200, (
            "A succeeded task must expose its integrity-checked result; "
            f"received HTTP {result_response.status_code}"
        )
        result = result_response.json()
        assert result["task_id"] == task_id
        assert result["project_id"] == project_id
        assert result["verification_status"] == "needs_human_review"
        assert result["human_review_required"] is True
        assert result["result"]["tool_execution_performed"] is False
        assert len(result["result_sha256"]) == 64

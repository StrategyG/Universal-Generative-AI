import json
from uuid import uuid4

import httpx
import pytest

from ugai_studio.client import (
    ExecutionLimits,
    ExecutionRequest,
    StudioExecutionClient,
    StudioUnavailable,
)


class TokenProvider:
    def __init__(self):
        self.calls = []

    async def get_access_token(self, **kwargs):
        self.calls.append(kwargs)
        return "studio-service-token"


@pytest.mark.asyncio
async def test_submit_execution_sends_digest_limits_and_identity_bound_token():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        payload = json.loads(request.content)
        return httpx.Response(
            202,
            json={
                "execution_id": str(uuid4()),
                "task_id": payload["task_id"],
                "state": "ACCEPTED",
            },
        )

    provider = TokenProvider()
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = StudioExecutionClient(
        base_url="https://studio.example",
        resource="https://studio.example",
        token_provider=provider,
        http_client=http,
    )
    task_id, tenant_id = uuid4(), uuid4()
    receipt = await client.submit(
        ExecutionRequest(
            task_id=task_id,
            notebook_id=uuid4(),
            source_sha256="a" * 64,
            runtime_profile="python-3.12",
            limits=ExecutionLimits(cpu_millis=1500),
        ),
        actor_id="actor-1",
        tenant_id=tenant_id,
        request_id=uuid4(),
        idempotency_key=uuid4(),
    )
    request = captured["request"]
    assert receipt.task_id == task_id
    assert request.headers["Authorization"] == "Bearer studio-service-token"
    assert request.headers["Idempotency-Key"]
    assert provider.calls[0]["actor_id"] == "actor-1"
    assert provider.calls[0]["tenant_id"] == tenant_id
    assert b"source_code" not in request.content
    await http.aclose()


def test_execution_rejects_unapproved_profile_and_invalid_digest():
    with pytest.raises(ValueError):
        ExecutionRequest(
            task_id=uuid4(),
            notebook_id=uuid4(),
            source_sha256="bad",
            runtime_profile="shell",
        ).validate()


@pytest.mark.asyncio
async def test_execution_submission_failure_is_uncertain_and_not_retried():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = StudioExecutionClient(
        base_url="https://studio.example",
        resource="https://studio.example",
        token_provider=TokenProvider(),
        http_client=http,
    )
    with pytest.raises(StudioUnavailable, match="reconcile before retry"):
        await client.submit(
            ExecutionRequest(
                task_id=uuid4(),
                notebook_id=uuid4(),
                source_sha256="b" * 64,
                runtime_profile="python-3.11",
            ),
            actor_id="actor-1",
            tenant_id=uuid4(),
            request_id=uuid4(),
            idempotency_key=uuid4(),
        )
    assert calls == 1
    await http.aclose()

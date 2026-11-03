import json
from uuid import uuid4

import httpx
import pytest

from ugai_studio.client import (
    MAX_RESPONSE_BYTES,
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


@pytest.mark.asyncio
async def test_execution_rejects_unknown_state_and_non_json_response():
    task_id = uuid4()
    responses = [
        httpx.Response(
            202,
            json={
                "execution_id": str(uuid4()),
                "task_id": str(task_id),
                "state": "MAGICALLY_DONE",
            },
        ),
        httpx.Response(202, text="accepted", headers={"content-type": "text/plain"}),
    ]
    for response in responses:
        http = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request, response=response: response)
        )
        client = StudioExecutionClient(
            base_url="https://studio.example",
            resource="https://studio.example",
            token_provider=TokenProvider(),
            http_client=http,
        )
        with pytest.raises(StudioUnavailable):
            await client.submit(
                ExecutionRequest(
                    task_id=task_id,
                    notebook_id=uuid4(),
                    source_sha256="c" * 64,
                    runtime_profile="python-3.12",
                ),
                actor_id="actor-1",
                tenant_id=uuid4(),
                request_id=uuid4(),
                idempotency_key=uuid4(),
            )
        await http.aclose()


@pytest.mark.asyncio
async def test_execution_rejects_oversized_response():
    task_id = uuid4()
    payload = {
        "execution_id": str(uuid4()),
        "task_id": str(task_id),
        "state": "ACCEPTED",
        "padding": "x" * MAX_RESPONSE_BYTES,
    }
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(202, json=payload))
    )
    client = StudioExecutionClient(
        base_url="https://studio.example",
        resource="https://studio.example",
        token_provider=TokenProvider(),
        http_client=http,
    )
    with pytest.raises(StudioUnavailable):
        await client.submit(
            ExecutionRequest(
                task_id=task_id,
                notebook_id=uuid4(),
                source_sha256="d" * 64,
                runtime_profile="python-3.11",
            ),
            actor_id="actor-1",
            tenant_id=uuid4(),
            request_id=uuid4(),
            idempotency_key=uuid4(),
        )
    await http.aclose()


@pytest.mark.asyncio
async def test_execution_rejects_wrong_task_receipt():
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                202,
                json={
                    "execution_id": str(uuid4()),
                    "task_id": str(uuid4()),
                    "state": "ACCEPTED",
                },
            )
        )
    )
    client = StudioExecutionClient(
        base_url="https://studio.example",
        resource="https://studio.example",
        token_provider=TokenProvider(),
        http_client=http,
    )
    with pytest.raises(StudioUnavailable):
        await client.submit(
            ExecutionRequest(
                task_id=uuid4(),
                notebook_id=uuid4(),
                source_sha256="e" * 64,
                runtime_profile="python-3.11",
            ),
            actor_id="actor-1",
            tenant_id=uuid4(),
            request_id=uuid4(),
            idempotency_key=uuid4(),
        )
    await http.aclose()

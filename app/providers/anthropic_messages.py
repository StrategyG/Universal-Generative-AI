from __future__ import annotations

import json
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

import httpx

from app.ai_schemas import AICompletionRequest
from app.config import settings
from app.providers.native_text import NativeTextProvider, normalize_usage
from app.providers.prompting import build_prompts
from app.providers.openai_compatible_text import OpenAICompatibleTextProvider
from app.providers.text_errors import TextGenerationProviderError


class AnthropicMessagesProvider(NativeTextProvider):
    """Native Anthropic Messages API adapter (text generation and SSE)."""

    name = "anthropic-messages"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.anthropic.com",
        api_version: str = "2026-10-21",
        timeout_seconds: float = 90.0,
        transport: httpx.AsyncBaseTransport | None = None,
        model_id: str = "",
        model_revision: str = "",
    ) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise TextGenerationProviderError(
                "Anthropic endpoint must be an HTTPS URL without embedded credentials",
                code="configuration_error",
            )
        if not api_key.strip():
            raise TextGenerationProviderError(
                "Anthropic API key is not configured",
                code="configuration_error",
            )
        super().__init__(model, model_id, model_revision)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.api_version = api_version
        self.timeout_seconds = max(1.0, min(float(timeout_seconds), 600.0))
        self.transport = transport

    @classmethod
    def from_settings(cls) -> "AnthropicMessagesProvider":
        return cls(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            base_url=settings.anthropic_base_url,
            api_version=settings.anthropic_api_version,
            timeout_seconds=settings.text_generation_timeout_seconds,
            model_id=settings.anthropic_model_id,
            model_revision=settings.anthropic_model_revision,
        )

    def _headers(self) -> dict[str, str]:
        return {
            "content-type": "application/json",
            "accept": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": self.api_version,
        }

    def _extra_payload(self) -> dict[str, object]:
        """Additional Messages request fields; subclasses may override this hook."""
        return {}

    async def _complete_once(
        self,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> tuple[str, dict[str, int]]:
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "stream": False,
        }
        payload.update(self._extra_payload())
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds),
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
            ) as client:
                response = await client.post(
                    f"{self.base_url}/v1/messages",
                    headers=self._headers(),
                    json=payload,
                )
                OpenAICompatibleTextProvider._raise_for_status(response)
                data = response.json()
        except TextGenerationProviderError:
            raise
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise OpenAICompatibleTextProvider._request_error(exc) from exc
        except ValueError as exc:
            raise TextGenerationProviderError(
                "Anthropic returned invalid JSON",
                code="invalid_provider_response",
            ) from exc

        blocks = data.get("content") if isinstance(data, dict) else None
        if not isinstance(blocks, list):
            raise TextGenerationProviderError(
                "Anthropic returned an invalid Messages response",
                code="invalid_provider_response",
            )
        content = "".join(
            block.get("text", "")
            for block in blocks
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ).strip()
        if not content:
            raise TextGenerationProviderError(
                "Anthropic response did not contain text output",
                code="empty_provider_response",
            )
        usage = data.get("usage") or {}
        return content, normalize_usage(
            usage.get("input_tokens"), usage.get("output_tokens")
        )

    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds),
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
            ) as client:
                response = await client.get(
                    f"{self.base_url}/v1/models",
                    params={"limit": 1000},
                    headers=self._headers(),
                )
                OpenAICompatibleTextProvider._raise_for_status(response)
                data = response.json()
        except TextGenerationProviderError:
            raise
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise OpenAICompatibleTextProvider._request_error(exc) from exc
        except ValueError as exc:
            raise TextGenerationProviderError(
                "Anthropic model catalog returned invalid JSON",
                code="invalid_provider_response",
            ) from exc
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise TextGenerationProviderError(
                "Anthropic model catalog returned an unsupported response shape",
                code="unsupported_model_discovery",
            )
        return sorted({
            item["id"].strip()
            for item in items
            if isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and item["id"].strip()
        })

    async def stream(self, request: AICompletionRequest) -> AsyncIterator[str]:
        system, user = build_prompts(request)
        payload = {
            "model": self.model,
            "max_tokens": request.max_output_tokens,
            "temperature": request.temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "stream": True,
        }
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds),
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
            ) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/v1/messages",
                    headers={**self._headers(), "accept": "text/event-stream"},
                    json=payload,
                ) as response:
                    OpenAICompatibleTextProvider._raise_for_status(response)
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if not raw:
                            continue
                        try:
                            event = json.loads(raw)
                        except ValueError as exc:
                            raise TextGenerationProviderError(
                                "Anthropic returned a malformed streaming event",
                                code="invalid_provider_stream",
                            ) from exc
                        event_type = event.get("type")
                        if event_type == "error":
                            raise TextGenerationProviderError(
                                "Anthropic returned a streaming error event",
                                code="provider_stream_error",
                            )
                        delta = event.get("delta") or {}
                        if (
                            event_type == "content_block_delta"
                            and delta.get("type") == "text_delta"
                            and isinstance(delta.get("text"), str)
                            and delta["text"]
                        ):
                            yield delta["text"]
        except TextGenerationProviderError:
            raise
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise OpenAICompatibleTextProvider._request_error(exc) from exc

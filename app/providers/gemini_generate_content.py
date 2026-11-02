from __future__ import annotations

import json
from collections.abc import AsyncIterator
from urllib.parse import quote, urlsplit

import httpx

from app.ai_schemas import AICompletionRequest
from app.config import settings
from app.providers.native_text import NativeTextProvider, normalize_usage
from app.providers.prompting import build_prompts
from app.providers.openai_compatible_text import OpenAICompatibleTextProvider
from app.providers.text_errors import TextGenerationProviderError


class GeminiGenerateContentProvider(NativeTextProvider):
    """Native Google Gemini generateContent and streamGenerateContent adapter."""

    name = "gemini-generate-content"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout_seconds: float = 90.0,
        transport: httpx.AsyncBaseTransport | None = None,
        model_id: str = "",
        model_revision: str = "",
    ) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise TextGenerationProviderError(
                "Gemini endpoint must be an HTTPS URL without embedded credentials",
                code="configuration_error",
            )
        if not api_key.strip():
            raise TextGenerationProviderError(
                "Gemini API key is not configured",
                code="configuration_error",
            )
        super().__init__(model, model_id, model_revision)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = max(1.0, min(float(timeout_seconds), 600.0))
        self.transport = transport

    @classmethod
    def from_settings(cls) -> "GeminiGenerateContentProvider":
        return cls(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            base_url=settings.gemini_base_url,
            timeout_seconds=settings.text_generation_timeout_seconds,
            model_id=settings.gemini_model_id,
            model_revision=settings.gemini_model_revision,
        )

    def _headers(self) -> dict[str, str]:
        return {
            "content-type": "application/json",
            "accept": "application/json",
            "x-goog-api-key": self.api_key,
        }

    def _model_url(self, method: str) -> str:
        model = quote(self.model, safe="-._")
        return f"{self.base_url}/models/{model}:{method}"

    @staticmethod
    def _extract_text(data: dict) -> str:
        texts = []
        for candidate in data.get("candidates") or []:
            content = candidate.get("content") or {}
            for part in content.get("parts") or []:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    texts.append(part["text"])
            if texts:
                break
        return "".join(texts).strip()

    @staticmethod
    def _usage(data: dict) -> dict[str, int]:
        usage = data.get("usageMetadata") or {}
        return normalize_usage(
            usage.get("promptTokenCount"),
            usage.get("candidatesTokenCount"),
        )

    async def _complete_once(
        self,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> tuple[str, dict[str, int]]:
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds),
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
            ) as client:
                response = await client.post(
                    self._model_url("generateContent"),
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
                "Gemini returned invalid JSON",
                code="invalid_provider_response",
            ) from exc

        if not isinstance(data, dict):
            raise TextGenerationProviderError(
                "Gemini returned an invalid generation response",
                code="invalid_provider_response",
            )
        content = self._extract_text(data)
        if not content:
            raise TextGenerationProviderError(
                "Gemini response did not contain text output",
                code="empty_provider_response",
            )
        return content, self._usage(data)

    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds),
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
            ) as client:
                response = await client.get(
                    f"{self.base_url}/models",
                    params={"pageSize": 1000},
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
                "Gemini model catalog returned invalid JSON",
                code="invalid_provider_response",
            ) from exc

        items = data.get("models") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise TextGenerationProviderError(
                "Gemini model catalog returned an unsupported response shape",
                code="unsupported_model_discovery",
            )
        model_ids: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if isinstance(name, str) and name.startswith("models/"):
                model_ids.add(name.removeprefix("models/"))
            base_model = item.get("baseModelId")
            if isinstance(base_model, str) and base_model:
                model_ids.add(base_model)
        return sorted(model_ids)

    async def stream(self, request: AICompletionRequest) -> AsyncIterator[str]:
        system, user = build_prompts(request)
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_output_tokens,
            },
        }
        url = self._model_url("streamGenerateContent")
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds),
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
            ) as client:
                async with client.stream(
                    "POST",
                    url,
                    params={"alt": "sse"},
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
                                "Gemini returned a malformed streaming event",
                                code="invalid_provider_stream",
                            ) from exc
                        if not isinstance(event, dict):
                            continue
                        content = self._extract_text(event)
                        if content:
                            yield content
        except TextGenerationProviderError:
            raise
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise OpenAICompatibleTextProvider._request_error(exc) from exc

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence

from app.ai_schemas import AICompletionRequest
from app.config import settings
from app.providers.openai_compatible_text import OpenAICompatibleTextProvider
from app.providers.anthropic_messages import AnthropicMessagesProvider
from app.providers.gemini_generate_content import GeminiGenerateContentProvider
from app.providers.text_base import TextModelProvider
from app.providers.text_errors import TextGenerationProviderError
from app.observability import current_request_id

logger = logging.getLogger(__name__)


class TextModelRouter:
    """Ordered, capability-aware router for compatible text model providers.

    The first provider is the preferred route. Later providers are explicit
    fallbacks, not silent substitutions. Permanent configuration errors are
    not retried against the same provider, but may proceed to a configured
    fallback. Streaming can fall back only before the first token is emitted.
    """

    def __init__(
        self,
        providers: Sequence[TextModelProvider],
        *,
        max_retries: int = 1,
        retry_backoff_seconds: float = 0.5,
    ) -> None:
        if not providers:
            raise ValueError("At least one text provider must be configured")
        names = [provider.name for provider in providers]
        if any(not isinstance(name, str) or not name.strip() for name in names):
            raise ValueError("Every text provider must have a stable non-empty name")
        if len(set(names)) != len(names):
            raise ValueError("Text provider names must be unique")
        self.providers = tuple(providers)
        self.max_retries = max(0, min(max_retries, 3))
        self.retry_backoff_seconds = max(0.0, min(retry_backoff_seconds, 10.0))

    @classmethod
    def from_settings(cls) -> "TextModelRouter":
        configured: dict[str, TextModelProvider] = {}

        primary_values = (
            settings.text_generation_base_url,
            settings.text_generation_model,
        )
        if any(primary_values):
            if not all(primary_values):
                raise TextGenerationProviderError(
                    "Primary OpenAI-compatible route requires both "
                    "TEXT_GENERATION_BASE_URL and TEXT_GENERATION_MODEL",
                    code="configuration_error",
                )
            configured["openai-compatible-chat"] = (
                OpenAICompatibleTextProvider.from_settings()
            )

        fallback_values = (
            settings.text_generation_fallback_base_url,
            settings.text_generation_fallback_model,
        )
        if any(fallback_values):
            if not all(fallback_values):
                raise TextGenerationProviderError(
                    "Fallback route requires both TEXT_GENERATION_FALLBACK_BASE_URL "
                    "and TEXT_GENERATION_FALLBACK_MODEL",
                    code="configuration_error",
                )
            fallback = OpenAICompatibleTextProvider(
                base_url=settings.text_generation_fallback_base_url,
                model=settings.text_generation_fallback_model,
                api_key=settings.text_generation_fallback_api_key,
                timeout_seconds=settings.text_generation_timeout_seconds,
                model_id=settings.text_generation_fallback_model_id,
                model_revision=settings.text_generation_fallback_model_revision,
            )
            fallback.name = "openai-compatible-chat-fallback"
            configured[fallback.name] = fallback

        anthropic_values = (settings.anthropic_api_key, settings.anthropic_model)
        if any(anthropic_values):
            if not all(anthropic_values):
                raise TextGenerationProviderError(
                    "Anthropic route requires both ANTHROPIC_API_KEY and ANTHROPIC_MODEL",
                    code="configuration_error",
                )
            provider = AnthropicMessagesProvider.from_settings()
            configured[provider.name] = provider

        gemini_values = (settings.gemini_api_key, settings.gemini_model)
        if any(gemini_values):
            if not all(gemini_values):
                raise TextGenerationProviderError(
                    "Gemini route requires both GEMINI_API_KEY and GEMINI_MODEL",
                    code="configuration_error",
                )
            provider = GeminiGenerateContentProvider.from_settings()
            configured[provider.name] = provider

        order = [
            item.strip()
            for item in settings.text_generation_provider_order.split(",")
            if item.strip()
        ]
        allowed_names = {
            "openai-compatible-chat",
            "openai-compatible-chat-fallback",
            "anthropic-messages",
            "gemini-generate-content",
        }
        unknown = sorted(set(order) - allowed_names)
        if unknown:
            raise TextGenerationProviderError(
                "Unknown provider names in TEXT_GENERATION_PROVIDER_ORDER: "
                + ", ".join(unknown),
                code="configuration_error",
            )
        ordered = [configured[name] for name in order if name in configured]
        omitted = sorted(set(configured) - set(order))
        if omitted:
            raise TextGenerationProviderError(
                "Configured providers are missing from TEXT_GENERATION_PROVIDER_ORDER: "
                + ", ".join(omitted),
                code="configuration_error",
            )
        if not ordered:
            raise TextGenerationProviderError(
                "No text generation provider is configured; configure an OpenAI-compatible, "
                "Anthropic, or Gemini route",
                code="configuration_error",
            )
        return cls(
            ordered,
            max_retries=settings.text_generation_max_retries,
            retry_backoff_seconds=settings.text_generation_retry_backoff_seconds,
        )

    def eligible_providers(self, *, streaming: bool = False) -> tuple[TextModelProvider, ...]:
        if not streaming:
            return self.providers
        return tuple(
            provider
            for provider in self.providers
            if getattr(getattr(provider, "capabilities", None), "streaming", False)
        )

    async def _wait_before_retry(
        self,
        error: TextGenerationProviderError,
        attempt: int,
    ) -> None:
        if error.retry_after_seconds is not None:
            delay = error.retry_after_seconds
        else:
            delay = self.retry_backoff_seconds * (2**attempt)
        await asyncio.sleep(min(max(delay, 0.0), 30.0))

    async def discover_models(self) -> dict:
        """Inspect the model catalog for each configured route without running inference."""
        routes = []
        for provider in self.providers:
            list_models = getattr(provider, "list_models", None)
            if not callable(list_models):
                routes.append({
                    "provider": provider.name,
                    "configured_model": provider.model,
                    "status": "discovery_unsupported",
                    "configured_model_available": None,
                    "models": [],
                })
                continue
            try:
                model_ids = await list_models()
            except TextGenerationProviderError as exc:
                routes.append({
                    "provider": provider.name,
                    "configured_model": provider.model,
                    "status": "discovery_unavailable",
                    "configured_model_available": None,
                    "models": [],
                    "error_code": exc.code,
                })
                continue
            routes.append({
                "provider": provider.name,
                "configured_model": provider.model,
                "status": (
                    "available"
                    if provider.model in model_ids
                    else "configured_model_not_listed"
                ),
                "configured_model_available": provider.model in model_ids,
                "models": model_ids,
            })
        return {"routes": routes}

    def get_provider(self, provider_name: str) -> TextModelProvider:
        """Return one exact configured provider or fail closed."""
        if not isinstance(provider_name, str) or not provider_name.strip():
            raise TextGenerationProviderError(
                "An exact provider name is required for policy-routed inference",
                code="configuration_error",
            )
        for provider in self.providers:
            if provider.name == provider_name:
                return provider
        raise TextGenerationProviderError(
            "The policy-selected provider is not configured",
            code="provider_not_configured",
        )

    async def generate_with_provider(
        self,
        provider_name: str,
        request: AICompletionRequest,
        *,
        expected_model_id: str | None = None,
        expected_model_revision: str | None = None,
    ) -> dict:
        """Invoke only the named provider; never fall through to another route.

        Higher-level policy code is responsible for selecting an explicitly
        approved fallback and invoking it as a separate, auditable attempt.
        Expected immutable model identity is checked before any provider call.
        """
        if (expected_model_id is None) != (expected_model_revision is None):
            raise ValueError("expected_model_id_and_revision_must_be_supplied_together")

        provider = self.get_provider(provider_name)
        if expected_model_id is not None and (
            getattr(provider, "model_id", None) != expected_model_id
            or getattr(provider, "model_revision", None) != expected_model_revision
        ):
            raise TextGenerationProviderError(
                "Configured provider model identity does not match the approved route",
                code="model_revision_mismatch",
            )

        for attempt in range(self.max_retries + 1):
            try:
                result = await provider.generate(request)
                result["routing"] = {
                    "selected_provider": provider.name,
                    "fallback_used": False,
                    "policy_selected": True,
                    "model_id": getattr(provider, "model_id", ""),
                    "model_revision": getattr(provider, "model_revision", ""),
                }
                return result
            except TextGenerationProviderError as exc:
                if not exc.retryable or attempt >= self.max_retries:
                    raise
                await self._wait_before_retry(exc, attempt)

        raise TextGenerationProviderError(
            "The policy-selected provider exhausted its retry budget",
            code="provider_retry_exhausted",
        )

    async def generate(self, request: AICompletionRequest) -> dict:
        failures: list[TextGenerationProviderError] = []
        for provider in self.eligible_providers():
            for attempt in range(self.max_retries + 1):
                try:
                    result = await provider.generate(request)
                    result["routing"] = {
                        "selected_provider": provider.name,
                        "fallback_used": provider is not self.providers[0],
                    }
                    if provider is not self.providers[0]:
                        logger.warning(
                            "text_provider_fallback",
                            extra={
                                "provider": provider.name,
                                "model": provider.model,
                                "failure_count": len(failures),
                                "request_id": current_request_id(),
                            },
                        )
                    return result
                except TextGenerationProviderError as exc:
                    failures.append(exc)
                    if not exc.retryable or attempt >= self.max_retries:
                        break
                    await self._wait_before_retry(exc, attempt)

        if failures:
            last = failures[-1]
            raise TextGenerationProviderError(
                f"All configured text providers failed: {last}",
                code=last.code,
                status_code=last.status_code,
                retryable=last.retryable,
                retry_after_seconds=last.retry_after_seconds,
            ) from last
        raise TextGenerationProviderError(
            "No configured provider supports the requested operation",
            code="capability_unavailable",
        )

    async def stream(self, request: AICompletionRequest) -> AsyncIterator[str]:
        failures: list[TextGenerationProviderError] = []
        for provider in self.eligible_providers(streaming=True):
            for attempt in range(self.max_retries + 1):
                iterator = provider.stream(request).__aiter__()
                try:
                    first_chunk = await anext(iterator)
                except StopAsyncIteration:
                    return
                except TextGenerationProviderError as exc:
                    failures.append(exc)
                    if not exc.retryable or attempt >= self.max_retries:
                        break
                    await self._wait_before_retry(exc, attempt)
                    continue

                if provider is not self.providers[0]:
                    logger.warning(
                        "text_stream_fallback",
                        extra={
                            "provider": provider.name,
                            "model": provider.model,
                            "failure_count": len(failures),
                            "request_id": current_request_id(),
                        },
                    )
                # Once a token has been emitted, switching providers would
                # splice two different generations together; propagate later errors.
                yield first_chunk
                async for chunk in iterator:
                    yield chunk
                return

        if failures:
            last = failures[-1]
            raise TextGenerationProviderError(
                f"All streaming providers failed before the first token: {last}",
                code=last.code,
                status_code=last.status_code,
                retryable=last.retryable,
                retry_after_seconds=last.retry_after_seconds,
            ) from last
        raise TextGenerationProviderError(
            "No configured provider supports streaming",
            code="capability_unavailable",
        )

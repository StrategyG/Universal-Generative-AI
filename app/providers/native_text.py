from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from app.ai_schemas import AICompletionRequest, GenerationQualityMode
from app.providers.prompting import build_prompts, build_revision_prompts
from app.providers.text_base import TextModelCapabilities
from app.providers.text_errors import TextGenerationProviderError


class NativeTextProvider(ABC):
    """Shared prompt and quality-mode contract for native vendor APIs."""

    capabilities = TextModelCapabilities(streaming=True)

    def __init__(self, model: str, model_id: str = "", model_revision: str = "") -> None:
        self.model = model.strip()
        self.model_id = model_id.strip()
        self.model_revision = model_revision.strip()
        if not self.model:
            raise TextGenerationProviderError(
                "Provider model name must be configured",
                code="configuration_error",
            )

    @abstractmethod
    async def _complete_once(
        self,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> tuple[str, dict[str, int]]:
        raise NotImplementedError

    @abstractmethod
    async def list_models(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def stream(self, request: AICompletionRequest) -> AsyncIterator[str]:
        raise NotImplementedError

    async def generate(self, request: AICompletionRequest) -> dict:
        system, user = build_prompts(request)
        draft, usage = await self._complete_once(
            system,
            user,
            request.max_output_tokens,
            request.temperature,
        )
        if request.quality_mode == GenerationQualityMode.SINGLE:
            return {
                "provider": self.name,
                "model": self.model,
                "domain": request.domain,
                "quality_mode": request.quality_mode,
                "draft": None,
                "critique": None,
                "final_content": draft,
                "review_type": "none",
                "verified": False,
                "usage": usage,
            }

        review_prompt, _ = build_revision_prompts(request, system, draft, "")
        critique, critique_usage = await self._complete_once(
            system, review_prompt, min(request.max_output_tokens, 2048), 0.1
        )
        _, revision_prompt = build_revision_prompts(request, system, draft, critique)
        final_content, revision_usage = await self._complete_once(
            system, revision_prompt, request.max_output_tokens,
            max(0.0, min(request.temperature, 0.3)),
        )
        combined: dict[str, int] = {}
        for usage_part in (usage, critique_usage, revision_usage):
            for key, value in usage_part.items():
                combined[key] = combined.get(key, 0) + value
        return {
            "provider": self.name,
            "model": self.model,
            "domain": request.domain,
            "quality_mode": request.quality_mode,
            "draft": draft,
            "critique": critique,
            "final_content": final_content,
            "review_type": "same_model_critique_and_revision",
            "verified": False,
            "usage": combined,
        }


def normalize_usage(input_tokens: object, output_tokens: object) -> dict[str, int]:
    input_count = input_tokens if isinstance(input_tokens, int) and input_tokens >= 0 else 0
    output_count = output_tokens if isinstance(output_tokens, int) and output_tokens >= 0 else 0
    return {
        "prompt_tokens": input_count,
        "completion_tokens": output_count,
        "total_tokens": input_count + output_count,
    }

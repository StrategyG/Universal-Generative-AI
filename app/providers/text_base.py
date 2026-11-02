from dataclasses import dataclass
from typing import AsyncIterator, Protocol

from app.ai_schemas import AICompletionRequest


@dataclass(frozen=True)
class TextModelCapabilities:
    streaming: bool = False
    tool_calling: bool = False
    structured_output: bool = False
    vision: bool = False
    audio: bool = False
    video: bool = False


class TextModelProvider(Protocol):
    name: str
    model: str
    model_id: str
    model_revision: str
    capabilities: TextModelCapabilities

    async def generate(self, request: AICompletionRequest) -> dict:
        ...

    def stream(self, request: AICompletionRequest) -> AsyncIterator[str]:
        ...

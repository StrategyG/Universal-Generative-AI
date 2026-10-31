from abc import ABC, abstractmethod
from dataclasses import dataclass
from app.schemas import TaskType

@dataclass
class GenerationResult:
    output_asset: str | None
    metadata: dict

class ModelProvider(ABC):
    name: str
    supported_tasks: set[TaskType]

    @abstractmethod
    async def generate(self, task: TaskType, prompt: str | None,
                       input_asset: str | None, options: dict) -> GenerationResult:
        """Run one inference request. Implementations must enforce their own resource limits."""

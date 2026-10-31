from app.providers.base import ModelProvider, GenerationResult
from app.schemas import TaskType

class MockProvider(ModelProvider):
    name = "mock"
    supported_tasks = set(TaskType)

    async def generate(self, task: TaskType, prompt: str | None,
                       input_asset: str | None, options: dict) -> GenerationResult:
        # Explicitly a test adapter: never represents real model inference.
        return GenerationResult(
            output_asset=None,
            metadata={"provider": self.name, "simulated": True,
                      "task": task.value, "note": "No model inference was performed."},
        )

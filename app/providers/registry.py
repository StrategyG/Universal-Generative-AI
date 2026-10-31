from app.providers.base import ModelProvider
from app.providers.diffusers_t2i import DiffusersTextToImageProvider
from app.providers.mock import MockProvider
from app.schemas import TaskType

class ProviderRegistry:
    def __init__(self):
        self._providers: dict[str, ModelProvider] = {}
    def register(self, provider: ModelProvider) -> None:
        self._providers[provider.name] = provider
    def get(self, name: str) -> ModelProvider:
        if name not in self._providers:
            raise KeyError(f"Unknown model provider: {name}")
        return self._providers[name]
    def for_task(self, name: str, task: TaskType) -> ModelProvider:
        provider = self.get(name)
        if task not in provider.supported_tasks:
            raise ValueError(f"Provider {name} does not support {task.value}")
        return provider

registry = ProviderRegistry()
registry.register(MockProvider())
registry.register(DiffusersTextToImageProvider())

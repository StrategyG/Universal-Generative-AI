import pytest
from app.providers.registry import ProviderRegistry
from app.providers.mock import MockProvider
from app.schemas import TaskType

def test_registry_task_capabilities():
    registry = ProviderRegistry()
    registry.register(MockProvider())
    assert registry.for_task("mock", TaskType.IMAGE_TO_3D).name == "mock"

def test_unknown_provider_fails_closed():
    registry = ProviderRegistry()
    with pytest.raises(KeyError):
        registry.get("not-configured")

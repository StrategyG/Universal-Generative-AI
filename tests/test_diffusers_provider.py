import asyncio
import sys
from types import SimpleNamespace

import pytest

from app.providers.diffusers_t2i import DiffusersTextToImageProvider
from app.schemas import TaskType


def test_diffusers_provider_declares_only_text_to_image():
    provider = DiffusersTextToImageProvider()
    assert TaskType.TEXT_TO_IMAGE in provider.supported_tasks
    assert TaskType.IMAGE_TO_3D not in provider.supported_tasks


def test_diffusers_provider_rejects_missing_prompt():
    provider = DiffusersTextToImageProvider()
    with pytest.raises(ValueError, match="prompt"):
        asyncio.run(provider.generate(TaskType.TEXT_TO_IMAGE, None, None, {}))


def test_seed_zero_is_applied_and_recorded(monkeypatch, tmp_path):
    class FakeGenerator:
        def __init__(self, device):
            self.device = device
            self.seed = None

        def manual_seed(self, seed):
            self.seed = seed
            return self

    class FakeImage:
        def save(self, path, format):
            path.write_bytes(b"test-image")

    captured = {}

    def fake_pipeline(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(images=[FakeImage()])

    fake_torch = SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: False),
        Generator=FakeGenerator,
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setattr("app.providers.diffusers_t2i.settings.artifact_dir", str(tmp_path))

    provider = DiffusersTextToImageProvider()
    provider._pipeline = fake_pipeline
    result = provider._infer("test prompt", {"seed": 0, "width": 256, "height": 256})

    assert captured["generator"].seed == 0
    assert result.metadata["seed"] == 0

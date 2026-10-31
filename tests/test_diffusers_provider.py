import asyncio

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

import asyncio
from functools import partial
from pathlib import Path
from uuid import uuid4

from app.config import settings
from app.providers.base import GenerationResult, ModelProvider
from app.schemas import TaskType


class DiffusersTextToImageProvider(ModelProvider):
    """Local GPU inference adapter for a pinned Diffusers/SDXL checkpoint."""

    name = "diffusers-sdxl"
    supported_tasks = frozenset({TaskType.TEXT_TO_IMAGE})

    def __init__(self):
        self._pipeline = None

    def _load_pipeline(self):
        if self._pipeline is not None:
            return self._pipeline
        if not settings.image_model_id or not settings.image_model_revision:
            raise RuntimeError(
                "Set IMAGE_MODEL_ID and immutable IMAGE_MODEL_REVISION before enabling inference"
            )
        try:
            import torch
            from diffusers import StableDiffusionXLPipeline
        except ImportError as exc:
            raise RuntimeError(
                "Install the optional image dependencies: pip install -e '.[image]'"
            ) from exc

        if settings.gpu_required and not torch.cuda.is_available():
            raise RuntimeError("GPU is required but CUDA is not available")
        device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if device == "cuda" else torch.float32
        self._pipeline = StableDiffusionXLPipeline.from_pretrained(
            settings.image_model_id,
            revision=settings.image_model_revision,
            torch_dtype=dtype,
            use_safetensors=True,
        ).to(device)
        return self._pipeline

    def _infer(self, prompt: str, options: dict) -> GenerationResult:
        width = int(options.get("width", 1024))
        height = int(options.get("height", 1024))
        steps = int(options.get("steps", 25))
        if not (256 <= width <= 1024 and 256 <= height <= 1024):
            raise ValueError("width and height must be between 256 and 1024")
        if not (1 <= steps <= 50):
            raise ValueError("steps must be between 1 and 50")

        pipeline = self._load_pipeline()
        import torch
        seed = int(options.get("seed", 0))
        generator = torch.Generator(device="cuda" if torch.cuda.is_available() else "cpu")
        if seed:
            generator.manual_seed(seed)
        image = pipeline(
            prompt=prompt,
            width=width,
            height=height,
            num_inference_steps=steps,
            generator=generator,
        ).images[0]

        output_dir = Path(settings.artifact_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid4().hex}.png"
        output_path = output_dir / filename
        image.save(output_path, format="PNG")
        return GenerationResult(
            output_asset=str(output_path),
            metadata={
                "provider": self.name,
                "model_id": settings.image_model_id,
                "model_revision": settings.image_model_revision,
                "seed": seed,
                "width": width,
                "height": height,
                "steps": steps,
                "device": "cuda" if torch.cuda.is_available() else "cpu",
            },
        )

    async def generate(self, task: TaskType, prompt: str | None,
                       input_asset: str | None, options: dict) -> GenerationResult:
        if task != TaskType.TEXT_TO_IMAGE:
            raise ValueError(f"Unsupported task: {task.value}")
        if not prompt:
            raise ValueError("A prompt is required for text-to-image inference")
        return await asyncio.to_thread(partial(self._infer, prompt, options))

"""Best-effort discovery of real notebook runtime capabilities.

Reported values describe the current worker environment; they are not a security
attestation. Model/task support must still be explicitly reviewed by the operator.
"""
from __future__ import annotations

import platform
from typing import Any


def detect_runtime_capabilities(
    supported_tasks: list[str],
    *,
    capacity: int = 1,
) -> dict[str, Any]:
    if not supported_tasks:
        raise ValueError("At least one explicitly approved WORKER_SUPPORTED_TASKS item is required")

    result: dict[str, Any] = {
        "runtime_version": f"Python {platform.python_version()}",
        "gpu_model": None,
        "gpu_vram_gb": 0.0,
        "available_gpu_memory_gb": 0.0,
        "cuda_version": None,
        "frameworks": [],
        "supported_tasks": supported_tasks,
        "available_memory_gb": 0.0,
        "capacity": capacity,
    }

    try:
        import torch

        result["frameworks"].append(f"torch=={torch.__version__}")
        result["cuda_version"] = torch.version.cuda
        if torch.cuda.is_available():
            properties = torch.cuda.get_device_properties(0)
            result["gpu_model"] = properties.name
            result["gpu_vram_gb"] = round(properties.total_memory / (1024**3), 2)
            free_bytes, _ = torch.cuda.mem_get_info(0)
            result["available_gpu_memory_gb"] = round(free_bytes / (1024**3), 2)
    except ImportError:
        result["frameworks"].append("torch:not-installed")

    for package_name in ("diffusers", "transformers", "trimesh", "pyrender"):
        try:
            package = __import__(package_name)
            version = getattr(package, "__version__", "installed")
            result["frameworks"].append(f"{package_name}=={version}")
        except ImportError:
            continue

    try:
        import psutil

        result["available_memory_gb"] = round(
            psutil.virtual_memory().available / (1024**3), 2
        )
    except ImportError:
        # A zero value prevents selection for jobs that declare a positive RAM floor.
        pass

    return result

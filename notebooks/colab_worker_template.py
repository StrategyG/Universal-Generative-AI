"""Google Colab outbound-polling worker helper for the Universal Generative AI control plane.

This is a notebook helper template, not a model implementation.
Set API_URL, EXTERNAL_WORKER_TOKEN and WORKER_ID in notebook secrets.
Never commit secrets or print authorization headers.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from app.workers.client import ExternalGPUWorker
from app.workers.runtime import detect_runtime_capabilities


def run_with_handler(
    handler: Callable[[dict[str, Any]], str | tuple[str, dict[str, Any]]],
) -> None:
    """Run a separately reviewed model handler against the external GPU queue."""
    required = ("API_URL", "EXTERNAL_WORKER_TOKEN", "WORKER_ID", "WORKER_SUPPORTED_TASKS")
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError(f"Missing notebook secrets/environment values: {', '.join(missing)}")

    worker = ExternalGPUWorker(
        platform="colab",
        worker_id=os.environ["WORKER_ID"],
    )
    tasks = [item.strip() for item in os.environ["WORKER_SUPPORTED_TASKS"].split(",") if item.strip()]
    capabilities = detect_runtime_capabilities(tasks)
    try:
        worker.register(capabilities)
        worker.run_forever(handler)
    finally:
        worker.close()


# Notebook usage after implementing and validating handle_job(job):
# run_with_handler(handle_job)

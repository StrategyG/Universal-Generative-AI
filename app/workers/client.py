"""Outbound-polling client for Kaggle and Google Colab GPU workers.

Keep API_URL and EXTERNAL_WORKER_TOKEN in notebook secrets/environment variables.
Never print credentials or commit them to a notebook.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from threading import Event
from typing import Any

import requests


class ExternalGPUWorker:
    def __init__(
        self,
        platform: str,
        worker_id: str,
        *,
        api_url: str | None = None,
        token: str | None = None,
        request_timeout: int = 30,
    ) -> None:
        self.api_url = (api_url or os.environ["API_URL"]).rstrip("/")
        self.token = token or os.environ["EXTERNAL_WORKER_TOKEN"]
        if not self.api_url.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            raise ValueError("API_URL must use HTTPS except for local development")
        if len(worker_id) < 3:
            raise ValueError("worker_id must contain at least 3 characters")
        if request_timeout < 1:
            raise ValueError("request_timeout must be positive")

        self.platform = platform
        self.worker_id = worker_id
        self.request_timeout = request_timeout
        self.session = requests.Session()
        self.session.headers.update({"X-Worker-Token": self.token})

    def _post(self, path: str, payload: dict[str, Any]) -> Any:
        response = self.session.post(
            f"{self.api_url}/api/v1/external-gpu/{path}",
            json=payload,
            timeout=self.request_timeout,
        )
        response.raise_for_status()
        return response.json()

    def claim(self) -> dict[str, Any] | None:
        return self._post(
            "claim",
            {"platform": self.platform, "worker_id": self.worker_id},
        )

    def heartbeat(self, job_id: str) -> dict[str, Any]:
        return self._post(
            f"jobs/{job_id}/heartbeat",
            {"worker_id": self.worker_id},
        )

    def complete(
        self,
        job_id: str,
        output_asset: str,
        metadata: dict[str, str | int | float | bool] | None = None,
    ) -> dict[str, Any]:
        return self._post(
            f"jobs/{job_id}/complete",
            {
                "worker_id": self.worker_id,
                "output_asset": output_asset,
                "metadata": metadata or {},
            },
        )

    def fail(self, job_id: str, error: str) -> dict[str, Any]:
        return self._post(
            f"jobs/{job_id}/fail",
            {"worker_id": self.worker_id, "error": error[:1000]},
        )

    def run_forever(
        self,
        handler: Callable[[dict[str, Any]], str | tuple[str, dict[str, Any]]],
        poll_seconds: int = 15,
        stop_event: Event | None = None,
    ) -> None:
        """Poll until stopped; handler returns an asset URI and optional provenance."""
        if poll_seconds < 1:
            raise ValueError("poll_seconds must be positive")
        stop = stop_event or Event()
        backoff = poll_seconds

        while not stop.is_set():
            try:
                job = self.claim()
                backoff = poll_seconds
            except requests.RequestException:
                stop.wait(backoff)
                backoff = min(backoff * 2, 300)
                continue

            if not job:
                stop.wait(poll_seconds)
                continue

            job_id = job["job_id"]
            try:
                result = handler(job)
                if isinstance(result, tuple):
                    output_asset, metadata = result
                else:
                    output_asset, metadata = result, {}
                self.complete(job_id, output_asset, metadata)
            except Exception as exc:  # noqa: BLE001 - report arbitrary model-handler failures to the queue
                try:
                    self.fail(job_id, str(exc))
                except requests.RequestException:
                    # The lease will expire and the server can retry the job.
                    pass

    def close(self) -> None:
        self.session.close()

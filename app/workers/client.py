"""Outbound-polling client for Kaggle and Google Colab GPU workers.

Keep API_URL and EXTERNAL_WORKER_TOKEN in notebook secrets/environment variables.
Never print credentials or commit them to a notebook.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from threading import Event, Thread
from typing import Any
from urllib.parse import urlsplit

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
        heartbeat_interval: float = 300,
    ) -> None:
        self.api_url = (api_url or os.environ["API_URL"]).rstrip("/")
        self.token = token or os.environ["EXTERNAL_WORKER_TOKEN"]
        parsed_url = urlsplit(self.api_url)
        local_http = (
            parsed_url.scheme == "http"
            and parsed_url.hostname in {"localhost", "127.0.0.1"}
        )
        if parsed_url.scheme != "https" and not local_http:
            raise ValueError("API_URL must use HTTPS except for localhost development")
        if not parsed_url.netloc:
            raise ValueError("API_URL must contain a valid host")
        if not self.token:
            raise ValueError("EXTERNAL_WORKER_TOKEN must not be empty")
        if len(worker_id) < 3:
            raise ValueError("worker_id must contain at least 3 characters")
        if request_timeout < 1:
            raise ValueError("request_timeout must be positive")
        if not 0 < heartbeat_interval < 900:
            raise ValueError("heartbeat_interval must be greater than 0 and below lease duration")

        self.platform = platform
        self.worker_id = worker_id
        self.request_timeout = request_timeout
        self.heartbeat_interval = heartbeat_interval
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

    def _heartbeat_while_running(
        self,
        job_id: str,
        stop_event: Event,
        lease_lost: Event,
    ) -> None:
        """Renew a claimed lease from a dedicated session while inference runs."""
        url = f"{self.api_url}/api/v1/external-gpu/jobs/{job_id}/heartbeat"
        backoff = 2
        with requests.Session() as session:
            session.headers.update({"X-Worker-Token": self.token})
            while not stop_event.wait(self.heartbeat_interval):
                try:
                    response = session.post(
                        url,
                        json={"worker_id": self.worker_id},
                        timeout=self.request_timeout,
                    )
                    if response.status_code in {401, 403, 404, 409}:
                        lease_lost.set()
                        stop_event.set()
                        return
                    response.raise_for_status()
                    backoff = 2
                except requests.RequestException as exc:
                    if isinstance(exc, requests.HTTPError) and exc.response is not None:
                        if exc.response.status_code in {401, 403, 404, 409}:
                            lease_lost.set()
                            stop_event.set()
                            return
                    if stop_event.wait(backoff):
                        return
                    backoff = min(backoff * 2, 60)

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
        """Poll until stopped; renew the lease while a model handler is running."""
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
            heartbeat_stop = Event()
            lease_lost = Event()
            heartbeat_thread = Thread(
                target=self._heartbeat_while_running,
                args=(job_id, heartbeat_stop, lease_lost),
                name=f"gpu-heartbeat-{self.worker_id}",
                daemon=True,
            )
            try:
                heartbeat_thread.start()
                result = handler(job)
            except Exception as exc:  # noqa: BLE001 - report arbitrary model-handler failures
                heartbeat_stop.set()
                heartbeat_thread.join(timeout=self.request_timeout + 1)
                try:
                    self.fail(job_id, str(exc))
                except requests.RequestException:
                    # The lease will expire and the server can retry the job.
                    pass
                continue

            heartbeat_stop.set()
            heartbeat_thread.join(timeout=self.request_timeout + 1)
            if lease_lost.is_set():
                # Do not report success against a lease the server has rejected.
                continue

            try:
                if isinstance(result, tuple):
                    output_asset, metadata = result
                else:
                    output_asset, metadata = result, {}
                self.complete(job_id, output_asset, metadata)
            except Exception as exc:  # noqa: BLE001 - report completion/handler failures
                try:
                    self.fail(job_id, str(exc))
                except requests.RequestException:
                    pass

    def close(self) -> None:
        self.session.close()

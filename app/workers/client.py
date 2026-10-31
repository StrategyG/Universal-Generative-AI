"""Minimal outbound-polling client for Kaggle/Colab notebook runtimes.

The notebook must supply API_URL and EXTERNAL_WORKER_TOKEN as environment
variables or notebook secrets. Never print the token or embed it in a notebook.
"""
import os
import time
import requests


class ExternalGPUWorker:
    def __init__(self, platform: str, worker_id: str):
        self.api_url = os.environ["API_URL"].rstrip("/")
        self.token = os.environ["EXTERNAL_WORKER_TOKEN"]
        self.platform = platform
        self.worker_id = worker_id
        self.session = requests.Session()
        self.session.headers.update({"X-Worker-Token": self.token})

    def claim(self):
        response = self.session.post(
            f"{self.api_url}/api/v1/external-gpu/claim",
            json={"platform": self.platform, "worker_id": self.worker_id},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def heartbeat(self, job_id: str):
        response = self.session.post(
            f"{self.api_url}/api/v1/external-gpu/jobs/{job_id}/heartbeat",
            json={"worker_id": self.worker_id},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def complete(self, job_id: str, output_asset: str):
        response = self.session.post(
            f"{self.api_url}/api/v1/external-gpu/jobs/{job_id}/complete",
            json={"worker_id": self.worker_id, "output_asset": output_asset},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def fail(self, job_id: str, error: str):
        response = self.session.post(
            f"{self.api_url}/api/v1/external-gpu/jobs/{job_id}/fail",
            json={"worker_id": self.worker_id, "error": error[:1000]},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def run_forever(self, handler, poll_seconds: int = 15):
        while True:
            job = self.claim()
            if not job:
                time.sleep(poll_seconds)
                continue
            try:
                output_asset = handler(job)
                self.complete(job["job_id"], output_asset)
            except Exception as exc:
                self.fail(job["job_id"], str(exc))

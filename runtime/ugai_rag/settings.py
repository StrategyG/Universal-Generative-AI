from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime configuration. Secrets are injected through the environment."""

    api_bearer_token: str = ""
    institutional_gateway_url: str = ""
    institutional_service_key: str = ""
    request_timeout_seconds: float = 15.0
    max_query_chars: int = 2000

    @classmethod
    def from_env(cls) -> "Settings":
        raw_timeout = os.getenv("UGAI_RAG_TIMEOUT_SECONDS", "15")
        try:
            timeout = float(raw_timeout)
        except ValueError as exc:
            raise ValueError("UGAI_RAG_TIMEOUT_SECONDS must be numeric") from exc
        if not 1 <= timeout <= 60:
            raise ValueError("UGAI_RAG_TIMEOUT_SECONDS must be between 1 and 60")
        return cls(
            api_bearer_token=os.getenv("UGAI_API_BEARER_TOKEN", "").strip(),
            institutional_gateway_url=os.getenv(
                "UGAI_INSTITUTIONAL_RAG_GATEWAY_URL", ""
            ).strip().rstrip("/"),
            institutional_service_key=os.getenv("UGAI_INSTITUTIONAL_SERVICE_KEY", ""),
            request_timeout_seconds=timeout,
        )

    @property
    def gateway_configured(self) -> bool:
        if not self.institutional_gateway_url or not self.institutional_service_key:
            return False
        parsed = urlsplit(self.institutional_gateway_url)
        if parsed.scheme == "https" and parsed.netloc:
            return True
        return parsed.scheme == "http" and parsed.hostname in {
            "localhost", "127.0.0.1", "::1"
        }

    @property
    def api_auth_configured(self) -> bool:
        return len(self.api_bearer_token) >= 32

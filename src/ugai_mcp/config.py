"""Validated, secret-free configuration for the IM19 remote MCP adapter."""

from __future__ import annotations

import ipaddress
import math
import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit


class ConfigurationError(ValueError):
    """Raised when remote MCP configuration is unsafe or incomplete."""


_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_TOOL_NAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.-]{0,127}$")


def _canonical_host(value: str, setting: str) -> str:
    candidate = value.strip().removesuffix(".")
    if (
        not candidate
        or any(char.isspace() or ord(char) < 33 for char in candidate)
        or any(char in candidate for char in "/:@?#*\\")
    ):
        raise ConfigurationError(f"{setting} must contain exact DNS hostnames only")
    try:
        host = candidate.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ConfigurationError(f"{setting} contains an invalid DNS hostname") from exc

    labels = host.split(".")
    if (
        len(host) > 253
        or len(labels) < 2
        or any(not _DNS_LABEL.fullmatch(label) for label in labels)
    ):
        raise ConfigurationError(f"{setting} contains an invalid DNS hostname")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return host
    raise ConfigurationError(f"{setting} must not contain IP-literal hosts")


def _validate_https_uri(
    value: str,
    setting: str,
    *,
    require_mcp_path: bool = False,
) -> tuple[str, int | None]:
    if not value or value != value.strip() or any(char.isspace() for char in value):
        raise ConfigurationError(f"{setting} must be a non-empty absolute HTTPS URI")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ConfigurationError(f"{setting} must be a valid absolute HTTPS URI") from exc
    if parsed.scheme != "https" or not parsed.hostname:
        raise ConfigurationError(f"{setting} must be an absolute HTTPS URI")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ConfigurationError(f"{setting} must not contain credentials, query, or fragment")
    if port not in (None, 443):
        raise ConfigurationError(f"{setting} must use the default HTTPS port")
    if require_mcp_path and parsed.path != "/mcp":
        raise ConfigurationError("IM19_MCP_URL must point to the exact /mcp resource")
    return _canonical_host(parsed.hostname, setting), port


@dataclass(frozen=True, slots=True)
class IM19Config:
    endpoint: str
    resource: str
    allowed_hosts: frozenset[str]
    allowed_tools: frozenset[str]
    request_timeout_seconds: float = 20.0
    max_result_bytes: int = 1_000_000

    def __post_init__(self) -> None:
        allowed_hosts = frozenset(
            _canonical_host(host, "allowed_hosts") for host in self.allowed_hosts
        )
        if not allowed_hosts:
            raise ConfigurationError("At least one exact DNS host must be allowlisted")
        endpoint_host, _ = _validate_https_uri(
            self.endpoint, "endpoint", require_mcp_path=True
        )
        resource_host, _ = _validate_https_uri(self.resource, "resource")
        if endpoint_host not in allowed_hosts or resource_host != endpoint_host:
            raise ConfigurationError("Endpoint/resource host must match the exact host allowlist")
        if not math.isfinite(self.request_timeout_seconds) or not (
            0 < self.request_timeout_seconds <= 120
        ):
            raise ConfigurationError("MCP timeout must be finite and between 0 and 120 seconds")
        if not 1_024 <= self.max_result_bytes <= 10_000_000:
            raise ConfigurationError("MCP max result size must be between 1 KiB and 10 MB")

        tool_values = list(self.allowed_tools)
        if len(tool_values) > 128 or len(tool_values) != len(set(tool_values)):
            raise ConfigurationError("Tool allowlist contains duplicate or excessive entries")
        if any(
            not isinstance(name, str) or not _TOOL_NAME.fullmatch(name)
            for name in tool_values
        ):
            raise ConfigurationError("Tool allowlist contains an invalid tool name")
        object.__setattr__(self, "allowed_hosts", allowed_hosts)
        object.__setattr__(self, "allowed_tools", frozenset(tool_values))

    @classmethod
    def from_env(cls) -> IM19Config:
        endpoint = os.getenv("IM19_MCP_URL", "").strip()
        resource = os.getenv("IM19_MCP_RESOURCE", "").strip()
        raw_hosts = os.getenv("IM19_MCP_ALLOWED_HOSTS", "")
        raw_tools = os.getenv("IM19_ALLOWED_READ_TOOLS", "")
        try:
            timeout = float(os.getenv("IM19_MCP_TIMEOUT_SECONDS", "20"))
            max_bytes = int(os.getenv("IM19_MCP_MAX_RESULT_BYTES", "1000000"))
        except ValueError as exc:
            raise ConfigurationError("Invalid MCP timeout or response-size setting") from exc

        host_items = [item.strip() for item in raw_hosts.split(",")]
        if not raw_hosts.strip() or any(not item for item in host_items):
            raise ConfigurationError("IM19_MCP_ALLOWED_HOSTS must contain exact DNS hostnames")
        normalized_hosts = [
            _canonical_host(item, "IM19_MCP_ALLOWED_HOSTS") for item in host_items
        ]
        if len(normalized_hosts) != len(set(normalized_hosts)):
            raise ConfigurationError("IM19_MCP_ALLOWED_HOSTS contains duplicate entries")

        tool_items = [item.strip() for item in raw_tools.split(",") if item.strip()]
        if raw_tools.strip() and (
            any(not item.strip() for item in raw_tools.split(","))
            or len(tool_items) != len(set(tool_items))
        ):
            raise ConfigurationError("IM19_ALLOWED_READ_TOOLS contains duplicate or empty entries")

        return cls(
            endpoint=endpoint,
            resource=resource,
            allowed_hosts=frozenset(normalized_hosts),
            allowed_tools=frozenset(tool_items),
            request_timeout_seconds=timeout,
            max_result_bytes=max_bytes,
        )

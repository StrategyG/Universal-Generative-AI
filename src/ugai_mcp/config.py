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


_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_TOOL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def _canonical_host(value: str, setting: str) -> str:
    candidate = value.strip()
    if candidate.endswith("."):
        candidate = candidate[:-1]
    if not candidate or any(c in candidate for c in " /:@?#*\\"):
        raise ConfigurationError(f"{setting} must contain exact DNS hostnames only")
    if any(c.isspace() or ord(c) < 33 for c in candidate):
        raise ConfigurationError(f"{setting} contains an invalid hostname")
    try:
        host = candidate.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ConfigurationError(f"{setting} contains an invalid hostname") from exc

    if not host or len(host) > 253:
        raise ConfigurationError(f"{setting} contains an invalid hostname")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ConfigurationError(f"{setting} must not contain IP-literal hosts")

    labels = host.split(".")
    if len(labels) < 2 or any(not _HOST_LABEL.fullmatch(label) for label in labels):
        raise ConfigurationError(f"{setting} contains an invalid DNS hostname")
    return host


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
        normalized_hosts = [_canonical_host(item, "IM19_MCP_ALLOWED_HOSTS") for item in host_items]
        if len(normalized_hosts) != len(set(normalized_hosts)):
            raise ConfigurationError("IM19_MCP_ALLOWED_HOSTS contains duplicate host entries")
        allowed_hosts = frozenset(normalized_hosts)

        endpoint_host, _ = _validate_https_uri(
            endpoint, "IM19_MCP_URL", require_mcp_path=True
        )
        resource_host, _ = _validate_https_uri(resource, "IM19_MCP_RESOURCE")
        if endpoint_host not in allowed_hosts:
            raise ConfigurationError("IM19_MCP_URL host is not in IM19_MCP_ALLOWED_HOSTS")
        if resource_host != endpoint_host:
            raise ConfigurationError("IM19_MCP_RESOURCE host must match IM19_MCP_URL host")

        if not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise ConfigurationError("MCP timeout must be finite and between 0 and 120 seconds")
        if not 1_024 <= max_bytes <= 10_000_000:
            raise ConfigurationError("MCP max result size must be between 1 KiB and 10 MB")

        tool_items = [item.strip() for item in raw_tools.split(",") if item.strip()]
        if len(tool_items) > 128:
            raise ConfigurationError("At most 128 IM19 tools may be allowlisted")
        if any(not _TOOL_NAME.fullmatch(item) for item in tool_items):
            raise ConfigurationError("IM19_ALLOWED_READ_TOOLS contains an invalid tool name")
        if len(tool_items) != len(set(tool_items)):
            raise ConfigurationError("IM19_ALLOWED_READ_TOOLS contains duplicate tool names")

        return cls(
            endpoint=endpoint,
            resource=resource,
            allowed_hosts=allowed_hosts,
            allowed_tools=frozenset(tool_items),
            request_timeout_seconds=timeout,
            max_result_bytes=max_bytes,
        )

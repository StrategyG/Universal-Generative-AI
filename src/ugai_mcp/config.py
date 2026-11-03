"""Strict, secret-free configuration for the remote IM19 MCP adapter."""

from __future__ import annotations

import ipaddress
import math
import os
import re
from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit


class ConfigurationError(ValueError):
    """Raised when remote MCP configuration is unsafe or incomplete."""


_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_TOOL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def _normalize_host(host: str, *, setting: str) -> str:
    """Return a canonical DNS hostname; IP literals and wildcard entries are denied."""
    try:
        normalized = host.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ConfigurationError(f"{setting} contains an invalid hostname") from exc

    if not normalized or len(normalized) > 253 or "*" in normalized:
        raise ConfigurationError(f"{setting} must contain exact DNS hostnames")
    try:
        ipaddress.ip_address(normalized)
    except ValueError:
        pass
    else:
        raise ConfigurationError(f"{setting} must not contain IP-literal hosts")

    labels = normalized.split(".")
    if len(labels) < 2 or any(not _HOST_LABEL.fullmatch(label) for label in labels):
        raise ConfigurationError(f"{setting} contains an invalid DNS hostname")
    return normalized


def _parse_https_url(value: str, *, setting: str, path: str | None = None) -> SplitResult:
    if not value or value != value.strip() or any(char.isspace() for char in value):
        raise ConfigurationError(f"{setting} must be a non-empty absolute HTTPS URL")

    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ConfigurationError(f"{setting} is malformed") from exc

    if parsed.scheme != "https" or not parsed.netloc or not parsed.hostname:
        raise ConfigurationError(f"{setting} must be an absolute HTTPS URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ConfigurationError(f"{setting} must not contain credentials, query, or fragment")
    if port not in (None, 443):
        raise ConfigurationError(f"{setting} must use the HTTPS default port")
    if path is not None and parsed.path != path:
        raise ConfigurationError(f"{setting} must point to the exact {path} path")

    return parsed


@dataclass(frozen=True, slots=True)
class IM19Config:
    endpoint: str
    resource: str
    allowed_tools: frozenset[str]
    allowed_hosts: frozenset[str]
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

        if not math.isfinite(timeout) or timeout <= 0 or timeout > 120:
            raise ConfigurationError("MCP timeout must be finite and between 0 and 120 seconds")
        if max_bytes < 1_024 or max_bytes > 10_000_000:
            raise ConfigurationError("MCP max result size must be between 1 KiB and 10 MB")

        endpoint_url = _parse_https_url(
            endpoint,
            setting="IM19_MCP_URL",
            path="/mcp",
        )
        resource_url = _parse_https_url(
            resource,
            setting="IM19_MCP_RESOURCE",
        )

        host_items = [item.strip() for item in raw_hosts.split(",") if item.strip()]
        if not host_items:
            raise ConfigurationError("IM19_MCP_ALLOWED_HOSTS must explicitly allow the MCP host")
        allowed_hosts = frozenset(
            _normalize_host(item, setting="IM19_MCP_ALLOWED_HOSTS")
            for item in host_items
        )
        if len(allowed_hosts) != len(host_items):
            raise ConfigurationError("IM19_MCP_ALLOWED_HOSTS contains duplicate host entries")

        endpoint_host = _normalize_host(
            endpoint_url.hostname or "",
            setting="IM19_MCP_URL",
        )
        resource_host = _normalize_host(
            resource_url.hostname or "",
            setting="IM19_MCP_RESOURCE",
        )
        if endpoint_host not in allowed_hosts:
            raise ConfigurationError("IM19_MCP_URL host is not in IM19_MCP_ALLOWED_HOSTS")
        if resource_host != endpoint_host:
            raise ConfigurationError("IM19_MCP_RESOURCE must use the same host as IM19_MCP_URL")

        tool_items = [item.strip() for item in raw_tools.split(",") if item.strip()]
        if len(tool_items) > 128:
            raise ConfigurationError("At most 128 IM19 tools may be allowlisted")
        if any(not _TOOL_NAME.fullmatch(item) for item in tool_items):
            raise ConfigurationError("IM19_ALLOWED_READ_TOOLS contains an invalid tool name")
        if len(set(tool_items)) != len(tool_items):
            raise ConfigurationError("IM19_ALLOWED_READ_TOOLS contains duplicate tool names")

        return cls(
            endpoint=endpoint,
            resource=resource,
            allowed_tools=frozenset(tool_items),
            allowed_hosts=allowed_hosts,
            request_timeout_seconds=timeout,
            max_result_bytes=max_bytes,
        )

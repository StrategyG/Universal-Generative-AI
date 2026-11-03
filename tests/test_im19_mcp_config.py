import pytest

from ugai_mcp.config import ConfigurationError, IM19Config


def set_valid_env(monkeypatch):
    monkeypatch.setenv("IM19_MCP_URL", "https://im19.example/mcp")
    monkeypatch.setenv("IM19_MCP_RESOURCE", "https://im19.example")


def test_config_requires_https_and_exact_mcp_path(monkeypatch):
    monkeypatch.setenv("IM19_MCP_URL", "http://im19.example/mcp")
    monkeypatch.setenv("IM19_MCP_RESOURCE", "https://im19.example")
    with pytest.raises(ConfigurationError):
        IM19Config.from_env()


def test_config_accepts_https_mcp_endpoint(monkeypatch):
    set_valid_env(monkeypatch)
    monkeypatch.setenv("IM19_ALLOWED_READ_TOOLS", "drive_search_files,youtube_get_channel")
    config = IM19Config.from_env()
    assert config.endpoint == "https://im19.example/mcp"
    assert config.allowed_tools == frozenset(
        {"drive_search_files", "youtube_get_channel"}
    )


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://user:pass@im19.example/mcp",
        "https://im19.example/other",
        "https://im19.example:invalid/mcp",
        "https://im19.example/mcp?token=secret",
    ],
)
def test_config_rejects_unsafe_endpoint(monkeypatch, endpoint):
    monkeypatch.setenv("IM19_MCP_URL", endpoint)
    monkeypatch.setenv("IM19_MCP_RESOURCE", "https://im19.example")
    with pytest.raises(ConfigurationError):
        IM19Config.from_env()


@pytest.mark.parametrize(
    "resource",
    [
        "",
        "im19-resource",
        "https://user:pass@im19.example",
        "https://im19.example?token=secret",
    ],
)
def test_config_rejects_invalid_resource_uri(monkeypatch, resource):
    monkeypatch.setenv("IM19_MCP_URL", "https://im19.example/mcp")
    monkeypatch.setenv("IM19_MCP_RESOURCE", resource)
    with pytest.raises(ConfigurationError):
        IM19Config.from_env()


def test_config_rejects_nan_timeout(monkeypatch):
    set_valid_env(monkeypatch)
    monkeypatch.setenv("IM19_MCP_TIMEOUT_SECONDS", "nan")
    with pytest.raises(ConfigurationError):
        IM19Config.from_env()

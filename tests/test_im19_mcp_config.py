import pytest

from ugai_mcp.config import ConfigurationError, IM19Config


def test_config_requires_https_and_exact_mcp_path(monkeypatch):
    monkeypatch.setenv("IM19_MCP_URL", "http://im19.example/mcp")
    monkeypatch.setenv("IM19_MCP_RESOURCE", "https://im19.example")
    with pytest.raises(ConfigurationError):
        IM19Config.from_env()


def test_config_accepts_https_mcp_endpoint(monkeypatch):
    monkeypatch.setenv("IM19_MCP_URL", "https://im19.example/mcp")
    monkeypatch.setenv("IM19_MCP_RESOURCE", "https://im19.example")
    monkeypatch.setenv("IM19_ALLOWED_READ_TOOLS", "drive_search,youtube_search")
    config = IM19Config.from_env()
    assert config.endpoint == "https://im19.example/mcp"
    assert config.allowed_tools == frozenset({"drive_search", "youtube_search"})


def test_config_rejects_url_credentials(monkeypatch):
    monkeypatch.setenv("IM19_MCP_URL", "https://user:pass@im19.example/mcp")
    monkeypatch.setenv("IM19_MCP_RESOURCE", "https://im19.example")
    with pytest.raises(ConfigurationError):
        IM19Config.from_env()

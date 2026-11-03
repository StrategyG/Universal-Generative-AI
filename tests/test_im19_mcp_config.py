import pytest

from ugai_mcp.config import ConfigurationError, IM19Config


def configure(monkeypatch, **overrides):
    values = {
        "IM19_MCP_URL": "https://im19.example/mcp",
        "IM19_MCP_RESOURCE": "https://im19.example",
        "IM19_MCP_ALLOWED_HOSTS": "im19.example",
        "IM19_ALLOWED_READ_TOOLS": "drive_search,youtube_search",
        "IM19_MCP_TIMEOUT_SECONDS": "20",
        "IM19_MCP_MAX_RESULT_BYTES": "1000000",
    }
    values.update(overrides)
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_config_requires_https(monkeypatch):
    configure(monkeypatch, IM19_MCP_URL="http://im19.example/mcp")
    with pytest.raises(ConfigurationError, match="HTTPS"):
        IM19Config.from_env()


def test_config_accepts_exact_allowlisted_https_mcp_endpoint(monkeypatch):
    configure(monkeypatch)
    config = IM19Config.from_env()

    assert config.endpoint == "https://im19.example/mcp"
    assert config.allowed_tools == frozenset({"drive_search", "youtube_search"})
    assert config.allowed_hosts == frozenset({"im19.example"})


def test_config_rejects_url_credentials(monkeypatch):
    configure(monkeypatch, IM19_MCP_URL="https://user:pass@im19.example/mcp")
    with pytest.raises(ConfigurationError, match="credentials"):
        IM19Config.from_env()


def test_config_requires_explicit_host_allowlist(monkeypatch):
    configure(monkeypatch, IM19_MCP_ALLOWED_HOSTS="")
    with pytest.raises(ConfigurationError, match="IM19_MCP_ALLOWED_HOSTS"):
        IM19Config.from_env()


def test_config_rejects_endpoint_outside_host_allowlist(monkeypatch):
    configure(monkeypatch, IM19_MCP_URL="https://attacker.example/mcp")
    with pytest.raises(ConfigurationError, match="not in IM19_MCP_ALLOWED_HOSTS"):
        IM19Config.from_env()


def test_config_rejects_resource_on_different_host(monkeypatch):
    configure(monkeypatch, IM19_MCP_RESOURCE="https://other.example/mcp")
    with pytest.raises(ConfigurationError, match="same host"):
        IM19Config.from_env()


def test_config_rejects_non_https_resource(monkeypatch):
    configure(monkeypatch, IM19_MCP_RESOURCE="http://im19.example/mcp")
    with pytest.raises(ConfigurationError, match="HTTPS"):
        IM19Config.from_env()


def test_config_rejects_query_fragment_and_non_default_port(monkeypatch):
    configure(monkeypatch, IM19_MCP_URL="https://im19.example:8443/mcp")
    with pytest.raises(ConfigurationError, match="default port"):
        IM19Config.from_env()

    configure(monkeypatch, IM19_MCP_RESOURCE="https://im19.example/mcp?tenant=unsafe")
    with pytest.raises(ConfigurationError, match="query"):
        IM19Config.from_env()


def test_config_requires_exact_mcp_path(monkeypatch):
    configure(monkeypatch, IM19_MCP_URL="https://im19.example/mcp/")
    with pytest.raises(ConfigurationError, match="exact /mcp"):
        IM19Config.from_env()


@pytest.mark.parametrize("timeout", ["nan", "inf", "-inf", "0", "121"])
def test_config_rejects_non_finite_or_out_of_range_timeout(monkeypatch, timeout):
    configure(monkeypatch, IM19_MCP_TIMEOUT_SECONDS=timeout)
    with pytest.raises(ConfigurationError, match="timeout"):
        IM19Config.from_env()


def test_config_rejects_ip_literals_and_wildcards_in_allowlist(monkeypatch):
    configure(monkeypatch, IM19_MCP_ALLOWED_HOSTS="127.0.0.1")
    with pytest.raises(ConfigurationError, match="IP-literal"):
        IM19Config.from_env()

    configure(monkeypatch, IM19_MCP_ALLOWED_HOSTS="*.example")
    with pytest.raises(ConfigurationError, match="exact DNS"):
        IM19Config.from_env()


def test_config_rejects_duplicate_or_malformed_tool_names(monkeypatch):
    configure(monkeypatch, IM19_ALLOWED_READ_TOOLS="drive_search,drive_search")
    with pytest.raises(ConfigurationError, match="duplicate tool"):
        IM19Config.from_env()

    configure(monkeypatch, IM19_ALLOWED_READ_TOOLS="drive search")
    with pytest.raises(ConfigurationError, match="invalid tool"):
        IM19Config.from_env()

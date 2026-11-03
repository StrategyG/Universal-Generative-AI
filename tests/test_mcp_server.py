import asyncio

from app import mcp_server
from app.auth import Principal


def test_mcp_token_verifier_rejects_invalid_token(monkeypatch):
    def reject(_token):
        raise ValueError("bad token")

    monkeypatch.setattr(mcp_server, "decode_access_token", reject)
    assert asyncio.run(mcp_server.OIDCReadTokenVerifier().verify_token("invalid")) is None


def test_mcp_token_verifier_grants_only_read_scope(monkeypatch):
    claims = {
        "sub": "reader-1",
        "iss": "https://identity.example.test/",
        "aud": "universal-generative-ai",
        "exp": 2_000_000_000,
        "iat": 1_900_000_000,
        "tenant_id": "tenant-1",
        "roles": ["read_only"],
        "project_ids": ["project-1"],
    }
    monkeypatch.setattr(mcp_server, "decode_access_token", lambda _token: claims)

    access = asyncio.run(mcp_server.OIDCReadTokenVerifier().verify_token("valid-token"))

    assert access is not None
    assert access.client_id == "reader-1"
    assert access.scopes == ["ugai:read"]
    assert access.resource is None


def test_mcp_token_verifier_rejects_unknown_role(monkeypatch):
    claims = {
        "sub": "guest-1",
        "iss": "https://identity.example.test/",
        "aud": "universal-generative-ai",
        "exp": 2_000_000_000,
        "iat": 1_900_000_000,
        "tenant_id": "tenant-1",
        "roles": ["guest"],
        "project_ids": [],
    }
    monkeypatch.setattr(mcp_server, "decode_access_token", lambda _token: claims)

    assert asyncio.run(mcp_server.OIDCReadTokenVerifier().verify_token("guest-token")) is None

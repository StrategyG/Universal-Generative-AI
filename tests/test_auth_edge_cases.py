from __future__ import annotations

import asyncio
from types import SimpleNamespace

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app import auth
from app.auth import Principal
from app.config import settings


def configure_oidc(monkeypatch, *, environment="test", issuer="https://issuer.example.test/",
                   audience="ugai-test", jwks="https://issuer.example.test/jwks"):
    monkeypatch.setattr(settings, "auth_mode", "oidc")
    monkeypatch.setattr(settings, "environment", environment)
    monkeypatch.setattr(settings, "oidc_issuer", issuer)
    monkeypatch.setattr(settings, "oidc_audience", audience)
    monkeypatch.setattr(settings, "oidc_jwks_url", jwks)


def test_auth_configuration_rejects_unknown_mode(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "password")
    monkeypatch.setattr(settings, "environment", "test")
    with pytest.raises(RuntimeError, match="AUTH_MODE must be"):
        auth.validate_auth_configuration()


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("oidc_issuer", "OIDC_ISSUER"),
        ("oidc_audience", "OIDC_AUDIENCE"),
        ("oidc_jwks_url", "OIDC_JWKS_URL"),
    ],
)
def test_oidc_configuration_reports_each_missing_required_value(monkeypatch, field, message):
    configure_oidc(monkeypatch)
    monkeypatch.setattr(settings, field, "   ")
    with pytest.raises(RuntimeError, match=message):
        auth.validate_auth_configuration()


def test_production_oidc_requires_https_issuer_and_jwks(monkeypatch):
    configure_oidc(monkeypatch, environment="production", issuer="http://issuer.example.test/")
    with pytest.raises(RuntimeError, match="OIDC_ISSUER must use HTTPS"):
        auth.validate_auth_configuration()

    configure_oidc(monkeypatch, environment="prod", jwks="http://issuer.example.test/jwks")
    with pytest.raises(RuntimeError, match="OIDC_JWKS_URL must use HTTPS"):
        auth.validate_auth_configuration()


def test_valid_production_oidc_configuration_is_accepted(monkeypatch):
    configure_oidc(monkeypatch, environment="production")
    auth.validate_auth_configuration()


def test_principal_admin_property_is_tenant_scoped_role_metadata():
    ordinary = Principal("user", "tenant-a", frozenset({"developer"}), frozenset(), "oidc")
    tenant_admin = Principal("admin", "tenant-a", frozenset({"tenant_admin"}), frozenset(), "oidc")
    platform_admin = Principal("platform", "tenant-a", frozenset({"platform_admin"}), frozenset(), "oidc")
    assert ordinary.is_tenant_admin is False
    assert tenant_admin.is_tenant_admin is True
    assert platform_admin.is_tenant_admin is True


def test_get_current_principal_disabled_mode_is_development_only(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "disabled")
    monkeypatch.setattr(settings, "environment", "development")
    principal = asyncio.run(auth.get_current_principal(None))
    assert principal.subject == "local-development"
    assert principal.project_ids == frozenset({"*"})

    monkeypatch.setattr(settings, "environment", "production")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(auth.get_current_principal(None))
    assert exc.value.status_code == 503


def test_get_current_principal_rejects_non_bearer_scheme(monkeypatch):
    configure_oidc(monkeypatch)
    credentials = HTTPAuthorizationCredentials(scheme="Basic", credentials="not-a-bearer")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(auth.get_current_principal(credentials))
    assert exc.value.status_code == 401
    assert exc.value.headers["WWW-Authenticate"] == "Bearer"


def test_get_current_principal_maps_verified_claims(monkeypatch):
    configure_oidc(monkeypatch)
    monkeypatch.setattr(
        auth,
        "decode_access_token",
        lambda token: {
            "sub": " user-1 ",
            "tenant_id": " tenant-1 ",
            "roles": ["developer", "read_only"],
            "project_ids": ["project-1"],
        },
    )
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="signed-token")
    principal = asyncio.run(auth.get_current_principal(credentials))
    assert principal.subject == "user-1"
    assert principal.tenant_id == "tenant-1"
    assert principal.roles == frozenset({"developer", "read_only"})


def test_get_current_principal_hides_token_validation_details(monkeypatch):
    configure_oidc(monkeypatch)

    def reject(_token):
        raise jwt.InvalidSignatureError("private validation detail")

    monkeypatch.setattr(auth, "decode_access_token", reject)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="forged-token")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(auth.get_current_principal(credentials))
    assert exc.value.status_code == 401
    assert exc.value.detail == "Bearer token is invalid or expired"
    assert "private validation detail" not in exc.value.detail


def test_decode_access_token_rejects_non_object_claim_payload(monkeypatch):
    configure_oidc(monkeypatch)
    monkeypatch.setattr(
        auth,
        "_jwks_client",
        lambda _url: SimpleNamespace(
            get_signing_key_from_jwt=lambda _token: SimpleNamespace(key="test-key")
        ),
    )
    monkeypatch.setattr(jwt, "decode", lambda *_args, **_kwargs: ["not", "an", "object"])
    with pytest.raises(ValueError, match="claims must be an object"):
        auth.decode_access_token("test-token")


def test_authorization_helpers_cover_allowed_and_denied_paths():
    developer = Principal("developer", "tenant-a", frozenset({"developer"}), frozenset({"p1"}), "oidc")
    reader = Principal("reader", "tenant-a", frozenset({"read_only"}), frozenset({"p1"}), "oidc")
    auth.require_generation_role(developer)
    auth.require_job_read_role(reader)

    with pytest.raises(HTTPException) as generation_error:
        auth.require_generation_role(reader)
    assert generation_error.value.status_code == 403

    with pytest.raises(HTTPException) as read_error:
        auth.require_job_read_role(
            Principal("guest", "tenant-a", frozenset(), frozenset(), "oidc")
        )
    assert read_error.value.status_code == 403


def test_project_access_covers_local_wildcard_admin_and_negative_paths():
    local = Principal("local", "local", frozenset({"developer"}), frozenset(), "disabled")
    auth.ensure_project_access(local, None)

    wildcard = Principal("user", "tenant-a", frozenset(), frozenset({"*"}), "oidc")
    auth.ensure_project_access(wildcard, "any-project")

    platform = Principal("platform", "tenant-a", frozenset({"platform_admin"}), frozenset(), "oidc")
    auth.ensure_project_access(platform, "project-z")

    project_member = Principal("member", "tenant-a", frozenset(), frozenset({"project-a"}), "oidc")
    auth.ensure_project_access(project_member, "project-a")

    with pytest.raises(HTTPException) as missing:
        auth.ensure_project_access(project_member, " ")
    assert missing.value.status_code == 422

    with pytest.raises(HTTPException) as denied:
        auth.ensure_project_access(project_member, "project-b")
    assert denied.value.status_code == 403

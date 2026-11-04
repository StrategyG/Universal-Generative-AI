from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import auth
from app.auth import Principal, ensure_project_access, principal_from_claims, require_generation_role
from app.config import settings
from app.main import app


def _oidc_settings(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "oidc")
    monkeypatch.setattr(settings, "environment", "test")
    monkeypatch.setattr(settings, "oidc_issuer", "https://identity.example.test/")
    monkeypatch.setattr(settings, "oidc_audience", "universal-generative-ai")
    monkeypatch.setattr(settings, "oidc_jwks_url", "https://identity.example.test/.well-known/jwks.json")


def test_oidc_token_signature_issuer_and_audience_are_verified(monkeypatch):
    _oidc_settings(monkeypatch)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "user-1",
            "iss": settings.oidc_issuer,
            "aud": settings.oidc_audience,
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "tenant_id": "tenant-1",
            "roles": ["developer"],
            "project_ids": ["project-1"],
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )

    class FakeJwksClient:
        def get_signing_key_from_jwt(self, _token):
            return SimpleNamespace(key=public_key)

    monkeypatch.setattr(auth, "_jwks_client", lambda _url: FakeJwksClient())
    claims = auth.decode_access_token(token)
    principal = principal_from_claims(claims)

    assert principal.subject == "user-1"
    assert principal.tenant_id == "tenant-1"
    assert principal.roles == frozenset({"developer"})
    assert principal.project_ids == frozenset({"project-1"})
    assert principal.scopes == frozenset()


def test_oidc_token_with_wrong_audience_is_rejected(monkeypatch):
    _oidc_settings(monkeypatch)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "user-1",
            "iss": settings.oidc_issuer,
            "aud": "different-service",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )

    class FakeJwksClient:
        def get_signing_key_from_jwt(self, _token):
            return SimpleNamespace(key=private_key.public_key())

    monkeypatch.setattr(auth, "_jwks_client", lambda _url: FakeJwksClient())
    with pytest.raises(jwt.InvalidAudienceError):
        auth.decode_access_token(token)


def test_principal_requires_tenant_claim(monkeypatch):
    _oidc_settings(monkeypatch)
    with pytest.raises(ValueError, match="tenant claim"):
        principal_from_claims({"sub": "user-1", "roles": ["developer"]})


def test_generation_requires_authorized_role():
    principal = Principal(
        subject="reader-1",
        tenant_id="tenant-1",
        roles=frozenset({"read_only"}),
        project_ids=frozenset({"project-1"}),
        auth_mode="oidc",
    )
    with pytest.raises(HTTPException) as exc:
        require_generation_role(principal)
    assert exc.value.status_code == 403


def test_job_read_requires_an_explicit_read_role():
    principal = Principal(
        subject="unassigned-1",
        tenant_id="tenant-1",
        roles=frozenset(),
        project_ids=frozenset({"project-1"}),
        auth_mode="oidc",
    )
    with pytest.raises(HTTPException) as exc:
        auth.require_job_read_role(principal)
    assert exc.value.status_code == 403


def test_project_membership_is_enforced():
    principal = Principal(
        subject="developer-1",
        tenant_id="tenant-1",
        roles=frozenset({"developer"}),
        project_ids=frozenset({"project-1"}),
        auth_mode="oidc",
    )
    ensure_project_access(principal, "project-1")
    with pytest.raises(HTTPException) as exc:
        ensure_project_access(principal, "project-2")
    assert exc.value.status_code == 403


def test_production_rejects_disabled_authentication(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "disabled")
    monkeypatch.setattr(settings, "environment", "production")
    with pytest.raises(RuntimeError, match="AUTH_MODE=oidc"):
        auth.validate_auth_configuration()


def test_generation_jobs_are_scoped_to_tenant_owner_and_project(monkeypatch):
    _oidc_settings(monkeypatch)
    monkeypatch.setattr(settings, "generation_backend", "mock")
    principal_state = {
        "value": Principal(
            subject="owner-1",
            tenant_id="tenant-1",
            roles=frozenset({"developer"}),
            project_ids=frozenset({"project-1"}),
            auth_mode="oidc",
        )
    }
    app.dependency_overrides[auth.get_current_principal] = lambda: principal_state["value"]

    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/v1/generate",
                json={
                    "task": "text_to_image",
                    "prompt": "tenant-scoped test",
                    "project_id": "project-1",
                },
            )
            assert created.status_code == 200
            job_id = created.json()["job_id"]

            principal_state["value"] = Principal(
                subject="member-2",
                tenant_id="tenant-1",
                roles=frozenset({"read_only"}),
                project_ids=frozenset({"project-1"}),
                auth_mode="oidc",
            )
            project_member_read = client.get(f"/api/v1/jobs/{job_id}")
            assert project_member_read.status_code == 200

            principal_state["value"] = Principal(
                subject="member-3",
                tenant_id="tenant-1",
                roles=frozenset({"read_only"}),
                project_ids=frozenset({"project-2"}),
                auth_mode="oidc",
            )
            cross_project_read = client.get(f"/api/v1/jobs/{job_id}")
            assert cross_project_read.status_code == 404

            principal_state["value"] = Principal(
                subject="member-4",
                tenant_id="tenant-2",
                roles=frozenset({"tenant_admin"}),
                project_ids=frozenset({"project-1"}),
                auth_mode="oidc",
            )
            cross_tenant_read = client.get(f"/api/v1/jobs/{job_id}")
            assert cross_tenant_read.status_code == 404
    finally:
        app.dependency_overrides.pop(auth.get_current_principal, None)


def test_oidc_mode_requires_bearer_authentication(monkeypatch):
    _oidc_settings(monkeypatch)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/generate",
            json={"task": "text_to_image", "prompt": "unauthenticated", "project_id": "project-1"},
        )
    assert response.status_code == 401

def test_oidc_scope_claim_is_parsed_as_space_delimited_tokens(monkeypatch):
    _oidc_settings(monkeypatch)
    principal = principal_from_claims(
        {
            "sub": "user-1",
            "tenant_id": "tenant-1",
            "scope": "ugai:tasks:read ugai:tasks:write",
        }
    )
    assert principal.scopes == frozenset({"ugai:tasks:read", "ugai:tasks:write"})


def test_oidc_scope_array_is_supported_and_malformed_scope_is_rejected(monkeypatch):
    _oidc_settings(monkeypatch)
    principal = principal_from_claims(
        {
            "sub": "user-1",
            "tenant_id": "tenant-1",
            "scope": ["ugai:tasks:read", "ugai:tasks:cancel"],
        }
    )
    assert principal.scopes == frozenset({"ugai:tasks:read", "ugai:tasks:cancel"})
    with pytest.raises(ValueError, match="scope string or array"):
        principal_from_claims(
            {"sub": "user-1", "tenant_id": "tenant-1", "scope": {"admin": True}}
        )


def test_workspace_membership_uses_its_own_signed_claim(monkeypatch):
    _oidc_settings(monkeypatch)
    principal = principal_from_claims(
        {
            "sub": "user-1",
            "tenant_id": "tenant-1",
            "workspace_ids": ["workspace-1"],
        }
    )
    auth.ensure_workspace_access(principal, "workspace-1")
    with pytest.raises(HTTPException) as exc:
        auth.ensure_workspace_access(principal, "project-1")
    assert exc.value.status_code == 403


def test_task_scope_is_required_and_never_inferred_from_role(monkeypatch):
    _oidc_settings(monkeypatch)
    principal = Principal(
        subject="developer-1",
        tenant_id="tenant-1",
        roles=frozenset({"developer"}),
        project_ids=frozenset({"project-1"}),
        auth_mode="oidc",
    )
    with pytest.raises(HTTPException) as exc:
        auth.require_scope(principal, "ugai:tasks:write")
    assert exc.value.status_code == 403

    authorized = Principal(
        subject="developer-1",
        tenant_id="tenant-1",
        roles=frozenset({"developer"}),
        project_ids=frozenset({"project-1"}),
        auth_mode="oidc",
        scopes=frozenset({"ugai:tasks:write"}),
    )
    auth.require_scope(authorized, "ugai:tasks:write")
    with pytest.raises(HTTPException) as read_exc:
        auth.require_scope(authorized, "ugai:tasks:read")
    assert read_exc.value.status_code == 403


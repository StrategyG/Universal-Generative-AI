from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from functools import lru_cache
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool

from app.config import settings


_bearer = HTTPBearer(auto_error=False)
_PRODUCTION_ENVIRONMENTS = {"production", "prod"}
_GENERATION_ROLES = {"developer", "project_owner", "tenant_admin", "platform_admin"}
_JOB_READ_ROLES = _GENERATION_ROLES | {"read_only"}


@dataclass(frozen=True)
class Principal:
    """Authenticated caller derived from a verified identity-provider token."""

    subject: str
    tenant_id: str
    roles: frozenset[str]
    project_ids: frozenset[str]
    auth_mode: str
    issuer: str = ""

    @property
    def actor_id(self) -> str:
        """Stable issuer-scoped actor key; raw subjects are never cross-issuer IDs."""
        if self.auth_mode == "oidc" and not self.issuer.strip():
            raise ValueError("verified_oidc_issuer_required")
        canonical = json.dumps(
            [self.issuer, self.subject],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return "principal:" + hashlib.sha256(canonical).hexdigest()

    @property
    def is_tenant_admin(self) -> bool:
        # Platform administrators are still constrained to the tenant asserted
        # by the identity provider; this API does not provide cross-tenant bypass.
        return bool(self.roles.intersection({"tenant_admin", "platform_admin"}))


def validate_auth_configuration() -> None:
    """Fail closed when production authentication is disabled or misconfigured."""
    mode = settings.auth_mode.strip().lower()
    environment = settings.environment.strip().lower()

    if mode not in {"disabled", "oidc"}:
        raise RuntimeError("AUTH_MODE must be either 'disabled' or 'oidc'")

    if mode == "disabled":
        if environment in _PRODUCTION_ENVIRONMENTS:
            raise RuntimeError("AUTH_MODE=oidc is required in production")
        return

    missing = [
        name
        for name, value in (
            ("OIDC_ISSUER", settings.oidc_issuer),
            ("OIDC_AUDIENCE", settings.oidc_audience),
            ("OIDC_JWKS_URL", settings.oidc_jwks_url),
        )
        if not value.strip()
    ]
    if missing:
        raise RuntimeError(
            "OIDC authentication is not configured; missing " + ", ".join(missing)
        )

    if environment in _PRODUCTION_ENVIRONMENTS:
        if not settings.oidc_issuer.startswith("https://"):
            raise RuntimeError("OIDC_ISSUER must use HTTPS in production")
        if not settings.oidc_jwks_url.startswith("https://"):
            raise RuntimeError("OIDC_JWKS_URL must use HTTPS in production")


@lru_cache(maxsize=4)
def _jwks_client(jwks_url: str):
    try:
        from jwt import PyJWKClient
    except ImportError as exc:
        raise RuntimeError("OIDC authentication requires PyJWT[crypto]") from exc
    return PyJWKClient(jwks_url, cache_jwk_set=True, lifespan=300, timeout=5)


def decode_access_token(token: str) -> dict[str, Any]:
    """Verify signature and standard OIDC claims against the configured JWKS."""
    try:
        import jwt
    except ImportError as exc:
        raise RuntimeError("OIDC authentication requires PyJWT[crypto]") from exc

    signing_key = _jwks_client(settings.oidc_jwks_url).get_signing_key_from_jwt(token).key
    claims = jwt.decode(
        token,
        signing_key,
        algorithms=["RS256"],
        audience=settings.oidc_audience,
        issuer=settings.oidc_issuer,
        options={"require": ["sub", "iss", "aud", "exp", "iat"]},
        leeway=30,
    )
    if not isinstance(claims, dict):
        raise ValueError("OIDC token claims must be an object")
    return claims


def _string_set(value: Any, claim_name: str) -> frozenset[str]:
    if value is None:
        return frozenset()
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        values = value
    else:
        raise ValueError(f"OIDC claim '{claim_name}' must be a string or array of strings")
    return frozenset(item.strip() for item in values if item.strip())


def principal_from_claims(claims: dict[str, Any]) -> Principal:
    """Map verified OIDC claims into the platform's authorization context."""
    subject = claims.get("sub")
    tenant_id = claims.get(settings.oidc_tenant_claim)
    if not isinstance(subject, str) or not subject.strip():
        raise ValueError("OIDC subject is missing")
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError("Required tenant claim is missing")

    issuer = claims.get("iss")
    if not isinstance(issuer, str) or issuer != settings.oidc_issuer:
        raise ValueError("OIDC issuer is missing or does not match the configured issuer")

    roles = _string_set(claims.get(settings.oidc_roles_claim), settings.oidc_roles_claim)
    projects = _string_set(
        claims.get(settings.oidc_projects_claim),
        settings.oidc_projects_claim,
    )
    return Principal(
        subject=subject.strip(),
        tenant_id=tenant_id.strip(),
        roles=roles,
        project_ids=projects,
        auth_mode="oidc",
        issuer=issuer,
    )


async def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Principal:
    """Return a verified OIDC principal, or a development-only local principal."""
    mode = settings.auth_mode.strip().lower()
    environment = settings.environment.strip().lower()

    if mode == "disabled":
        if environment in _PRODUCTION_ENVIRONMENTS:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication is not configured",
            )
        return Principal(
            subject="local-development",
            tenant_id="local-development",
            roles=frozenset(_GENERATION_ROLES),
            project_ids=frozenset({"*"}),
            auth_mode="disabled",
            issuer="local-development",
        )

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer authentication is required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        claims = await run_in_threadpool(decode_access_token, credentials.credentials)
        return principal_from_claims(claims)
    except Exception as exc:  # noqa: BLE001 - return a uniform public auth error
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token is invalid or expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def require_generation_role(principal: Principal) -> None:
    if not principal.roles.intersection(_GENERATION_ROLES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The caller is not permitted to submit generation requests",
        )


def require_job_read_role(principal: Principal) -> None:
    if not principal.roles.intersection(_JOB_READ_ROLES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The caller is not permitted to read generation jobs",
        )


def ensure_project_access(principal: Principal, project_id: str | None) -> None:
    if principal.auth_mode == "disabled":
        return
    if not project_id or not project_id.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="project_id is required for authenticated generation requests",
        )
    if (
        "*" in principal.project_ids
        or "platform_admin" in principal.roles
        or project_id in principal.project_ids
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="The caller does not have access to the requested project",
    )

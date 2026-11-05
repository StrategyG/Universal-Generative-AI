import json
from urllib.parse import parse_qs, urlsplit

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_name: str = "Universal Generative AI"
    environment: str = "development"
    api_prefix: str = "/api/v1"
    max_upload_bytes: int = 50 * 1024 * 1024
    artifact_dir: str = "artifacts"
    generation_backend: str = "mock"
    text_generation_base_url: str = ""
    text_generation_api_key: str = ""
    text_generation_model: str = ""
    text_generation_model_id: str = ""
    text_generation_model_revision: str = ""
    text_generation_fallback_base_url: str = ""
    text_generation_fallback_api_key: str = ""
    text_generation_fallback_model: str = ""
    text_generation_fallback_model_id: str = ""
    text_generation_fallback_model_revision: str = ""
    text_generation_timeout_seconds: float = 90.0
    text_generation_max_retries: int = 1
    text_generation_retry_backoff_seconds: float = 0.5
    reasoning_route_catalog_json: str = ""
    reasoning_permitted_data_regions: str = "ap-southeast-1"
    reasoning_max_estimated_cost: float = Field(default=1.0, gt=0.0, le=100.0)
    text_generation_provider_order: str = (
        "openai-compatible-chat,openai-compatible-chat-fallback,"
        "anthropic-messages,gemini-generate-content"
    )
    anthropic_api_key: str = ""
    anthropic_model: str = ""
    anthropic_model_id: str = ""
    anthropic_model_revision: str = ""
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_api_version: str = "2026-10-21"
    gemini_api_key: str = ""
    gemini_model: str = ""
    gemini_model_id: str = ""
    gemini_model_revision: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gpu_required: bool = False
    image_model_id: str = ""
    image_model_revision: str = ""
    external_worker_token: str = ""
    worker_admin_token: str = ""
    database_url: str = ""
    workflow_task_api_enabled: bool = False
    workflow_database_url: str = ""
    workflow_payload_encryption_key: str = ""
    workflow_payload_key_id: str = "v1"
    workflow_payload_previous_keys_json: str = "{}"
    workflow_worker_enabled: bool = False
    workflow_worker_database_url: str = ""
    workflow_worker_tenant_id: str = ""
    workflow_worker_id: str = ""
    workflow_worker_poll_seconds: float = Field(default=2.0, ge=0.5, le=30.0)
    workflow_worker_lease_seconds: int = Field(default=60, ge=10, le=900)
    workflow_worker_heartbeat_seconds: int = Field(default=10, ge=1, le=300)
    workflow_worker_health_window_seconds: int = Field(default=60, ge=5, le=900)
    model_registry_enforcement: bool = False
    auth_mode: str = "disabled"
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    oidc_tenant_claim: str = "tenant_id"
    oidc_roles_claim: str = "roles"
    oidc_projects_claim: str = "project_ids"


settings = Settings()



def validate_database_configuration(config: Settings = settings) -> None:
    """Fail closed when production PostgreSQL transport is not fully authenticated."""
    environment = config.environment.strip().lower()
    if environment not in {"production", "prod"}:
        return
    database_url = config.database_url.strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required in production")
    try:
        parsed = urlsplit(database_url)
        query = parse_qs(parsed.query, keep_blank_values=True)
    except ValueError as exc:
        raise RuntimeError("DATABASE_URL is invalid") from exc
    modes = query.get("sslmode", [])
    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or not parsed.hostname
        or len(modes) != 1
        or modes[0].strip().lower() != "verify-full"
    ):
        raise RuntimeError(
            "Production DATABASE_URL must use PostgreSQL with exactly one sslmode=verify-full"
        )


def validate_workflow_task_configuration(config: Settings = settings) -> None:
    """Require a dedicated least-privilege PostgreSQL identity and payload key."""
    environment = config.environment.strip().lower()
    enabled = config.workflow_task_api_enabled
    if environment in {"production", "prod"} and not enabled:
        raise RuntimeError("WORKFLOW_TASK_API_ENABLED=true is required in production")
    if not enabled:
        return

    database_url = config.workflow_database_url.strip()
    if not database_url:
        raise RuntimeError("WORKFLOW_DATABASE_URL is required when the task API is enabled")
    if not config.workflow_payload_encryption_key.strip():
        raise RuntimeError("WORKFLOW_PAYLOAD_ENCRYPTION_KEY is required when the task API is enabled")
    if not config.workflow_payload_key_id.strip() or len(config.workflow_payload_key_id) > 64:
        raise RuntimeError("WORKFLOW_PAYLOAD_KEY_ID is invalid")
    try:
        previous_keys = json.loads(config.workflow_payload_previous_keys_json or "{}")
    except (TypeError, ValueError) as exc:
        raise RuntimeError("WORKFLOW_PAYLOAD_PREVIOUS_KEYS_JSON must be valid JSON") from exc
    if not isinstance(previous_keys, dict):
        raise RuntimeError("WORKFLOW_PAYLOAD_PREVIOUS_KEYS_JSON must be an object")
    for previous_id, previous_key in previous_keys.items():
        if (
            not isinstance(previous_id, str)
            or not previous_id.strip()
            or len(previous_id) > 64
            or previous_id == config.workflow_payload_key_id
            or not isinstance(previous_key, str)
            or not previous_key.strip()
        ):
            raise RuntimeError("WORKFLOW_PAYLOAD_PREVIOUS_KEYS_JSON contains an invalid key entry")
    try:
        parsed = urlsplit(database_url)
        query = parse_qs(parsed.query, keep_blank_values=True)
    except ValueError as exc:
        raise RuntimeError("WORKFLOW_DATABASE_URL is invalid") from exc
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        raise RuntimeError("WORKFLOW_DATABASE_URL must be a PostgreSQL URL")
    if environment in {"production", "prod"}:
        modes = query.get("sslmode", [])
        if len(modes) != 1 or modes[0].strip().lower() != "verify-full":
            raise RuntimeError("Production WORKFLOW_DATABASE_URL must use sslmode=verify-full")



def validate_workflow_worker_configuration(config: Settings = settings) -> None:
    """Fail closed for the separately credentialed Notebook reasoning worker."""
    if not config.workflow_worker_enabled:
        return
    if not config.workflow_task_api_enabled:
        raise RuntimeError("WORKFLOW_TASK_API_ENABLED=true is required for the worker")
    if not config.workflow_worker_tenant_id.strip() or len(config.workflow_worker_tenant_id) > 128:
        raise RuntimeError("WORKFLOW_WORKER_TENANT_ID is required and must be at most 128 characters")
    if not config.workflow_worker_id.strip() or len(config.workflow_worker_id) > 128:
        raise RuntimeError("WORKFLOW_WORKER_ID is required and must be at most 128 characters")
    if config.workflow_worker_heartbeat_seconds * 2 >= config.workflow_worker_lease_seconds:
        raise RuntimeError("WORKFLOW_WORKER_HEARTBEAT_SECONDS must be less than half the lease")

    raw = config.workflow_worker_database_url.strip()
    if not raw:
        raise RuntimeError("WORKFLOW_WORKER_DATABASE_URL is required when the worker is enabled")
    try:
        parsed = urlsplit(raw)
        api_parsed = urlsplit(config.workflow_database_url.strip())
        query = parse_qs(parsed.query, keep_blank_values=True)
    except ValueError as exc:
        raise RuntimeError("WORKFLOW_WORKER_DATABASE_URL is invalid") from exc
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        raise RuntimeError("WORKFLOW_WORKER_DATABASE_URL must be a PostgreSQL URL")
    if parsed.username == api_parsed.username:
        raise RuntimeError("Worker and API database logins must be distinct")
    if config.environment.strip().lower() in {"production", "prod"}:
        modes = query.get("sslmode", [])
        if len(modes) != 1 or modes[0].strip().lower() != "verify-full":
            raise RuntimeError("Production WORKFLOW_WORKER_DATABASE_URL must use sslmode=verify-full")

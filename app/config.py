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
    reasoning_max_estimated_cost: float = 1.0
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
    model_registry_enforcement: bool = False
    auth_mode: str = "disabled"
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    oidc_tenant_claim: str = "tenant_id"
    oidc_roles_claim: str = "roles"
    oidc_projects_claim: str = "project_ids"


settings = Settings()

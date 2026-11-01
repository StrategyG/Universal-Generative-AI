from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_name: str = "Universal Generative AI"
    environment: str = "development"
    api_prefix: str = "/api/v1"
    max_upload_bytes: int = 50 * 1024 * 1024
    artifact_dir: str = "artifacts"
    generation_backend: str = "mock"
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

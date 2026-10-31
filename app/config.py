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

settings = Settings()

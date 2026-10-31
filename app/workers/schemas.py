from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class WorkerPlatform(str, Enum):
    KAGGLE = "kaggle"
    COLAB = "colab"


class ExternalJobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"
    CANCELLED = "cancelled"


class ExternalJobCreate(BaseModel):
    platform: WorkerPlatform
    task: str = Field(min_length=1, max_length=100)
    input_asset: str = Field(min_length=1, max_length=2048)
    prompt: str | None = Field(default=None, max_length=4000)
    model_id: str = Field(min_length=1, max_length=256)
    model_revision: str = Field(min_length=1, max_length=128)
    options: dict[str, str | int | float | bool] = Field(default_factory=dict)
    min_gpu_vram_gb: float = Field(default=0, ge=0, le=1024)
    min_memory_gb: float = Field(default=0, ge=0, le=4096)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)


class ExternalJob(BaseModel):
    job_id: str
    platform: WorkerPlatform
    task: str
    status: ExternalJobStatus
    input_asset: str
    prompt: str | None
    model_id: str
    model_revision: str
    options: dict[str, str | int | float | bool]
    attempts: int = 0
    worker_id: str | None = None
    lease_expires_at: float | None = None
    next_attempt_at: float | None = None
    output_asset: str | None = None
    result_metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)
    min_gpu_vram_gb: float = 0
    min_memory_gb: float = 0
    idempotency_key: str | None = None
    error: str | None = None


class WorkerClaim(BaseModel):
    platform: WorkerPlatform
    worker_id: str = Field(min_length=3, max_length=128)


class WorkerHeartbeat(BaseModel):
    worker_id: str = Field(min_length=3, max_length=128)


class WorkerCompletion(BaseModel):
    worker_id: str = Field(min_length=3, max_length=128)
    output_asset: str = Field(min_length=1, max_length=2048)
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)


class WorkerFailure(BaseModel):
    worker_id: str = Field(min_length=3, max_length=128)
    error: str = Field(min_length=1, max_length=1000)


class WorkerProvisionRequest(BaseModel):
    worker_id: str = Field(min_length=3, max_length=128)
    platform: WorkerPlatform
    ttl_seconds: int = Field(default=86400, ge=300, le=604800)


class WorkerProvisionResponse(BaseModel):
    worker_id: str
    token: str
    token_expires_at: datetime


class WorkerRegistration(BaseModel):
    runtime_version: str = Field(min_length=1, max_length=128)
    gpu_model: str | None = Field(default=None, max_length=256)
    gpu_vram_gb: float = Field(default=0, ge=0, le=1024)
    available_gpu_memory_gb: float = Field(default=0, ge=0, le=1024)
    cuda_version: str | None = Field(default=None, max_length=64)
    frameworks: list[str] = Field(default_factory=list, max_length=64)
    supported_tasks: list[str] = Field(min_length=1, max_length=64)
    available_memory_gb: float = Field(default=0, ge=0, le=4096)
    capacity: int = Field(default=1, ge=1, le=32)


class WorkerRuntimeHeartbeat(BaseModel):
    available_gpu_memory_gb: float = Field(default=0, ge=0, le=1024)
    available_memory_gb: float = Field(default=0, ge=0, le=4096)


class WorkerProfile(BaseModel):
    worker_id: str
    platform: WorkerPlatform
    status: str
    runtime_version: str | None = None
    gpu_model: str | None = None
    gpu_vram_gb: float = 0
    available_gpu_memory_gb: float = 0
    cuda_version: str | None = None
    frameworks: list[str] = Field(default_factory=list)
    supported_tasks: list[str] = Field(default_factory=list)
    available_memory_gb: float = 0
    capacity: int = 1
    token_expires_at: datetime
    last_heartbeat_at: datetime | None = None

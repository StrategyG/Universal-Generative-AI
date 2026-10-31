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


class ExternalJobCreate(BaseModel):
    platform: WorkerPlatform
    task: str = Field(min_length=1, max_length=100)
    input_asset: str = Field(min_length=1, max_length=2048)
    prompt: str | None = Field(default=None, max_length=4000)
    model_id: str = Field(min_length=1, max_length=256)
    model_revision: str = Field(min_length=1, max_length=128)
    options: dict[str, str | int | float | bool] = Field(default_factory=dict)


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
    output_asset: str | None = None
    result_metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)
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

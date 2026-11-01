from enum import Enum

from pydantic import BaseModel, Field


class TaskType(str, Enum):
    TEXT_TO_IMAGE = "text_to_image"
    IMAGE_TO_3D = "image_to_3d"
    GLB_TO_VIDEO = "glb_to_video"
    TEXT_TO_VIDEO = "text_to_video"
    IMAGE_TO_VIDEO = "image_to_video"

class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

class GenerationRequest(BaseModel):
    task: TaskType
    prompt: str | None = Field(default=None, max_length=4000)
    input_asset: str | None = None
    project_id: str | None = Field(default=None, min_length=1, max_length=128)
    options: dict[str, str | int | float | bool] = Field(default_factory=dict)

class JobResponse(BaseModel):
    job_id: str
    task: TaskType
    status: JobStatus
    message: str
    output_asset: str | None = None

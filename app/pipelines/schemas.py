from enum import Enum

from pydantic import BaseModel, Field


class PipelineType(str, Enum):
    IMAGE_TO_3D = "image_to_3d"
    IMAGE_TO_VIDEO = "image_to_video"
    GLB_TO_VIDEO = "glb_to_video"


class PipelineRequest(BaseModel):
    workflow: PipelineType
    input_asset: str = Field(min_length=1, max_length=1024)
    prompt: str | None = Field(default=None, max_length=4000)
    options: dict[str, str | int | float | bool] = Field(default_factory=dict)


class PipelineStep(BaseModel):
    step_id: str
    task: str
    depends_on: list[str] = Field(default_factory=list)
    provider: str
    execution: str
    required_input: str
    expected_output: str
    resource_profile: str
    acceptance_checks: list[str]


class PipelinePlan(BaseModel):
    workflow: PipelineType
    status: str
    input_asset: str
    steps: list[PipelineStep]
    blocked_steps: list[str]
    warnings: list[str]

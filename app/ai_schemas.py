from enum import Enum

from pydantic import BaseModel, Field

from app.workflows.schemas import ProjectDomain


class GenerationQualityMode(str, Enum):
    SINGLE = "single"
    RIGOROUS = "rigorous"


class AICompletionRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=128)
    domain: ProjectDomain
    objective: str = Field(min_length=1, max_length=8000)
    context: str = Field(default="", max_length=20000)
    output_format: str = Field(
        default="Markdown with clear headings",
        min_length=1,
        max_length=120,
    )
    quality_mode: GenerationQualityMode = GenerationQualityMode.RIGOROUS
    temperature: float = Field(default=0.2, ge=0.0, le=1.2)
    max_output_tokens: int = Field(default=4096, ge=256, le=8192)


class AICompletionResponse(BaseModel):
    provider: str
    model: str
    domain: ProjectDomain
    quality_mode: GenerationQualityMode
    draft: str | None = None
    critique: str | None = None
    final_content: str
    review_type: str
    verified: bool = False
    usage: dict[str, int] = Field(default_factory=dict)
    routing: dict[str, str | bool] = Field(default_factory=dict)

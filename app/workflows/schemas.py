from enum import Enum

from pydantic import BaseModel, Field, field_validator


class ProjectDomain(str, Enum):
    CODING = "coding"
    FILM = "film"
    WORKFLOW = "workflow"


class SideEffect(str, Enum):
    NONE = "none"
    WORKSPACE_WRITE = "workspace_write"
    EXTERNAL_WRITE = "external_write"
    DEPLOY = "deploy"
    DELETE = "delete"
    PUBLISH = "publish"


class WorkflowStepRequest(BaseModel):
    step_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
    title: str = Field(min_length=1, max_length=160)
    action: str = Field(min_length=1, max_length=80)
    depends_on: list[str] = Field(default_factory=list, max_length=32)
    # Client-supplied hints are accepted for compatibility but never authorize execution.
    side_effect: SideEffect = SideEffect.NONE
    risk_score: int = Field(default=0, ge=0, le=5)

    @field_validator("depends_on")
    @classmethod
    def unique_dependencies(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("depends_on must not contain duplicates")
        return value


class WorkflowPlanRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=128)
    domain: ProjectDomain
    title: str = Field(min_length=1, max_length=160)
    objective: str = Field(min_length=1, max_length=4000)
    steps: list[WorkflowStepRequest] = Field(min_length=1, max_length=100)


class WorkflowTemplateRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=160)
    objective: str = Field(min_length=1, max_length=4000)


class PlannedStep(BaseModel):
    step_id: str
    title: str
    action: str
    depends_on: list[str]
    side_effect: SideEffect
    risk_score: int
    policy_rule: str
    requires_human_approval: bool
    execution_status: str = "not_configured"


class WorkflowPlan(BaseModel):
    project_id: str
    domain: ProjectDomain
    title: str
    objective: str
    status: str = "planning_only"
    execution_enabled: bool = False
    ordered_steps: list[PlannedStep]
    approval_required_steps: list[str]
    policy_version: str = "institutional-workflow-policy-v2"
    warnings: list[str]

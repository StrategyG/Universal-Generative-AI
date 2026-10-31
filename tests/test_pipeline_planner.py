import pytest

from app.pipelines.planner import build_pipeline_plan
from app.pipelines.schemas import PipelineRequest, PipelineType


def test_image_to_video_plan_has_ordered_dependencies():
    plan = build_pipeline_plan(PipelineRequest(
        workflow=PipelineType.IMAGE_TO_VIDEO,
        input_asset="asset://uploads/character.png",
    ))
    assert [step.step_id for step in plan.steps] == [
        "image_to_3d", "validate_glb", "rig_character", "generate_motion", "render_video"
    ]
    assert plan.steps[-1].depends_on == ["generate_motion"]
    assert plan.status == "blocked"
    assert len(plan.blocked_steps) == 5


def test_glb_to_video_rejects_image_input():
    with pytest.raises(ValueError, match="\.glb"):
        build_pipeline_plan(PipelineRequest(
            workflow=PipelineType.GLB_TO_VIDEO,
            input_asset="character.png",
        ))


def test_glb_to_video_plan():
    plan = build_pipeline_plan(PipelineRequest(
        workflow=PipelineType.GLB_TO_VIDEO,
        input_asset="asset://models/character.glb",
    ))
    assert [step.task for step in plan.steps] == [
        "validate_glb", "optimize_glb", "render_video"
    ]

from pathlib import PurePosixPath
from urllib.parse import urlparse

from app.pipelines.schemas import (
    PipelinePlan,
    PipelineRequest,
    PipelineStep,
    PipelineType,
)


_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
_GLTF_EXTENSIONS = {".glb"}


def _extension(asset: str) -> str:
    parsed = urlparse(asset)
    return PurePosixPath(parsed.path or asset).suffix.lower()


def _step(
    step_id: str,
    task: str,
    depends_on: list[str],
    required_input: str,
    expected_output: str,
    resource_profile: str,
    checks: list[str],
) -> PipelineStep:
    # Providers are deliberately unconfigured until a real worker is installed.
    return PipelineStep(
        step_id=step_id,
        task=task,
        depends_on=depends_on,
        provider="unconfigured",
        execution="not_implemented",
        required_input=required_input,
        expected_output=expected_output,
        resource_profile=resource_profile,
        acceptance_checks=checks,
    )


def build_pipeline_plan(request: PipelineRequest) -> PipelinePlan:
    ext = _extension(request.input_asset)
    if request.workflow in {PipelineType.IMAGE_TO_3D, PipelineType.IMAGE_TO_VIDEO}:
        if ext not in _IMAGE_EXTENSIONS:
            raise ValueError("This workflow requires a PNG, JPG, JPEG, or WebP input asset")
    elif ext not in _GLTF_EXTENSIONS:
        raise ValueError("glb_to_video requires a .glb input asset")

    steps: list[PipelineStep]
    if request.workflow == PipelineType.IMAGE_TO_3D:
        steps = [
            _step("image_to_3d", "image_to_3d", [], "image", "glb", "gpu-24gb",
                  ["GLB parses", "mesh is non-empty", "textures are embedded or referenced"]),
            _step("validate_glb", "validate_glb", ["image_to_3d"], "glb", "validated_glb",
                  "cpu-4gb", ["glTF 2.0 validation passes", "no missing buffers or textures"]),
        ]
    elif request.workflow == PipelineType.IMAGE_TO_VIDEO:
        steps = [
            _step("image_to_3d", "image_to_3d", [], "image", "glb", "gpu-24gb",
                  ["GLB parses", "mesh is non-empty", "textures are embedded or referenced"]),
            _step("validate_glb", "validate_glb", ["image_to_3d"], "glb", "validated_glb",
                  "cpu-4gb", ["glTF 2.0 validation passes", "no missing buffers or textures"]),
            _step("rig_character", "rig_3d", ["validate_glb"], "validated_glb", "rigged_glb",
                  "gpu-16gb", ["skeleton exists", "skin weights are normalized", "deformation test passes"]),
            _step("generate_motion", "generate_motion", ["rig_character"], "rigged_glb",
                  "animated_glb", "gpu-24gb",
                  ["animation clip exists", "timestamps are monotonic", "joint transforms are finite"]),
            _step("render_video", "render_video", ["generate_motion"], "animated_glb", "mp4",
                  "gpu-8gb-or-cpu", ["video decodes", "frame rate and duration match request", "audio policy is explicit"]),
        ]
    else:
        steps = [
            _step("validate_glb", "validate_glb", [], "glb", "validated_glb", "cpu-4gb",
                  ["glTF 2.0 validation passes", "no missing buffers or textures"]),
            _step("optimize_glb", "optimize_glb", ["validate_glb"], "validated_glb",
                  "optimized_glb", "cpu-8gb", ["mesh integrity preserved", "size budget respected"]),
            _step("render_video", "render_video", ["optimize_glb"], "optimized_glb", "mp4",
                  "gpu-8gb-or-cpu", ["video decodes", "frame rate and duration match request", "audio policy is explicit"]),
        ]

    blocked = [step.step_id for step in steps if step.execution != "configured"]
    return PipelinePlan(
        workflow=request.workflow,
        status="blocked" if blocked else "ready",
        input_asset=request.input_asset,
        steps=steps,
        blocked_steps=blocked,
        warnings=[
            "Planning only: no model inference, asset download, GPU allocation, or rendering was executed.",
            "All real providers are currently unconfigured; install and validate workers before execution.",
        ],
    )

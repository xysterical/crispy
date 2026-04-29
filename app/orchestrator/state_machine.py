from __future__ import annotations

from enum import StrEnum

from app.data.models import StageName


class PipelineMode(StrEnum):
    COPY_IMAGE_ONLY = "copy_image_only"
    VIDEO_ONLY = "video_only"
    FULL_MULTIMODAL = "full_multimodal"
    MARKETPLACE_MAIN_IMAGE = "marketplace_main_image"


PIPELINE_STAGE_PLANS: dict[str, list[str]] = {
    PipelineMode.COPY_IMAGE_ONLY.value: [
        StageName.INTAKE.value,
        StageName.PLANNING.value,
        StageName.DIVERGENCE.value,
        StageName.COPY_IMAGE_GENERATION.value,
        StageName.VISUAL_QUALITY_ASSESSMENT.value,
        StageName.EVALUATION_SELECTION.value,
    ],
    PipelineMode.MARKETPLACE_MAIN_IMAGE.value: [
        StageName.INTAKE.value,
        StageName.PLANNING.value,
        StageName.DIVERGENCE.value,
        StageName.COPY_IMAGE_GENERATION.value,
        StageName.VISUAL_QUALITY_ASSESSMENT.value,
        StageName.EVALUATION_SELECTION.value,
    ],
    PipelineMode.VIDEO_ONLY.value: [
        StageName.INTAKE.value,
        StageName.PLANNING.value,
        StageName.DIVERGENCE.value,
        StageName.VIDEO_SCRIPTING.value,
        StageName.STORYBOARD_IMAGE_GENERATION.value,
        StageName.VIDEO_GENERATION.value,
        StageName.VISUAL_QUALITY_ASSESSMENT.value,
        StageName.EVALUATION_SELECTION.value,
    ],
    PipelineMode.FULL_MULTIMODAL.value: [
        StageName.INTAKE.value,
        StageName.PLANNING.value,
        StageName.DIVERGENCE.value,
        StageName.COPY_IMAGE_GENERATION.value,
        StageName.VIDEO_SCRIPTING.value,
        StageName.STORYBOARD_IMAGE_GENERATION.value,
        StageName.VIDEO_GENERATION.value,
        StageName.VISUAL_QUALITY_ASSESSMENT.value,
        StageName.EVALUATION_SELECTION.value,
    ],
}

# Backward-compatible alias for tests and existing imports.
STAGE_ORDER: list[str] = PIPELINE_STAGE_PLANS[PipelineMode.FULL_MULTIMODAL.value]

# Stages that auto-approve under each approval mode.
# semi_auto: strategy stages auto-advance, creative/evaluation stages hold for human review.
# full_auto: every stage auto-advances.
# manual: no stage auto-advances (empty set).
AUTO_APPROVE_STAGES: dict[str, set[str]] = {
    "manual": set(),
    "semi_auto": {
        StageName.INTAKE.value,
        StageName.PLANNING.value,
        StageName.DIVERGENCE.value,
        StageName.VIDEO_SCRIPTING.value,
    },
    "full_auto": set(PIPELINE_STAGE_PLANS[PipelineMode.FULL_MULTIMODAL.value]),
}


def should_auto_approve(approval_mode: str, stage_name: str) -> bool:
    stages = AUTO_APPROVE_STAGES.get(approval_mode, set())
    return stage_name in stages


def stage_plan_for(pipeline_mode: str | None) -> list[str]:
    if not pipeline_mode:
        return list(STAGE_ORDER)
    return list(PIPELINE_STAGE_PLANS.get(pipeline_mode, STAGE_ORDER))


def next_stage(current_stage: str | None, pipeline_mode: str | None = None) -> str | None:
    stage_plan = stage_plan_for(pipeline_mode)
    if current_stage is None:
        return stage_plan[0]
    if current_stage not in stage_plan:
        return None
    idx = stage_plan.index(current_stage)
    if idx + 1 >= len(stage_plan):
        return None
    return stage_plan[idx + 1]

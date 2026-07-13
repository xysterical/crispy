from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.agents.registry import STAGE_CONTRACT_VERSION, stage_assignment
from app.data.models import StageName
from app.orchestrator.state_machine import stage_plan_for

ApprovalDefault = Literal["manual", "auto_strategy", "auto_full"]


@dataclass(frozen=True, slots=True)
class StageContract:
    stage_name: str
    runtime_handler: str
    produces: tuple[str, ...]
    required_inputs: tuple[str, ...] = ()
    optional_inputs: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    review_focus: tuple[str, ...] = ()
    success_criteria: tuple[str, ...] = ()
    human_approval_default: ApprovalDefault = "manual"
    contract_version: str = STAGE_CONTRACT_VERSION
    metadata: dict = field(default_factory=dict)

    @property
    def lead_agent(self) -> str:
        return stage_assignment(self.stage_name).lead_agent

    @property
    def collaborators(self) -> tuple[str, ...]:
        return stage_assignment(self.stage_name).collaborators

    def as_dict(self) -> dict:
        return {
            "stage_name": self.stage_name,
            "lead_agent": self.lead_agent,
            "collaborators": list(self.collaborators),
            "runtime_handler": self.runtime_handler,
            "required_inputs": list(self.required_inputs),
            "optional_inputs": list(self.optional_inputs),
            "produces": list(self.produces),
            "required_capabilities": list(self.required_capabilities),
            "review_focus": list(self.review_focus),
            "success_criteria": list(self.success_criteria),
            "human_approval_default": self.human_approval_default,
            "contract_version": self.contract_version,
            "metadata": dict(self.metadata),
        }


STAGE_CONTRACTS: dict[str, StageContract] = {
    StageName.INTAKE.value: StageContract(
        stage_name=StageName.INTAKE.value,
        runtime_handler="run_intake",
        produces=("product_intake", "asset_media_summary"),
        optional_inputs=("context", "business_context", "creative_specs", "uploaded_media"),
        required_capabilities=("text_generation", "image_understanding", "video_understanding"),
        review_focus=("product truth", "uploaded media summary", "run context"),
        success_criteria=("product and media context are normalized for downstream creative stages",),
        human_approval_default="auto_strategy",
    ),
    StageName.PLANNING.value: StageContract(
        stage_name=StageName.PLANNING.value,
        runtime_handler="run_planning",
        produces=("planning_brief",),
        required_inputs=("intake",),
        optional_inputs=("gm_lessons", "research_context", "gm_policy", "creative_specs"),
        required_capabilities=("text_generation",),
        review_focus=("strategy", "research and memory use", "creative constraints"),
        success_criteria=("planning brief converts product context into a defensible creative direction",),
        human_approval_default="auto_strategy",
    ),
    StageName.DIVERGENCE.value: StageContract(
        stage_name=StageName.DIVERGENCE.value,
        runtime_handler="run_divergence",
        produces=("variant_set",),
        required_inputs=("planning",),
        optional_inputs=("gm_policy", "creative_specs"),
        required_capabilities=("text_generation",),
        review_focus=("variant spread", "hook quality", "message diversity"),
        success_criteria=("variant set contains distinct angles and hooks ready for creative generation",),
        human_approval_default="auto_strategy",
    ),
    StageName.COPY_IMAGE_GENERATION.value: StageContract(
        stage_name=StageName.COPY_IMAGE_GENERATION.value,
        runtime_handler="run_copy_image_generation",
        produces=("copy_image_bundle", "variant_assets.image", "variant_assets.copy"),
        required_inputs=("variants",),
        optional_inputs=("intake", "business_context", "creative_specs", "historical_references"),
        required_capabilities=("text_generation", "image_generation", "reference_image_edit"),
        review_focus=("image product truth", "copy clarity", "platform fit"),
        success_criteria=("image and copy assets exist for required variants with product-safe prompts",),
        human_approval_default="manual",
    ),
    StageName.VIDEO_SCRIPTING.value: StageContract(
        stage_name=StageName.VIDEO_SCRIPTING.value,
        runtime_handler="run_video_scripting",
        produces=("video_script_pack",),
        required_inputs=("variants",),
        optional_inputs=("intake", "planning", "business_context", "creative_specs", "reference_bundle"),
        required_capabilities=("text_generation",),
        review_focus=("script structure", "shot sequence", "platform pacing"),
        success_criteria=("scripts provide enough structured direction for storyboard and video generation",),
        human_approval_default="auto_strategy",
    ),
    StageName.STORYBOARD_IMAGE_GENERATION.value: StageContract(
        stage_name=StageName.STORYBOARD_IMAGE_GENERATION.value,
        runtime_handler="run_storyboard_image_generation",
        produces=("storyboard_frames", "variant_assets.storyboard_frame"),
        required_inputs=("video_scripts",),
        optional_inputs=("intake", "planning", "creative_specs", "historical_references"),
        required_capabilities=("text_generation", "image_generation", "reference_image_edit"),
        review_focus=("frame continuity", "product visibility", "script alignment"),
        success_criteria=("storyboard frames are available for video segments that need visual references",),
        human_approval_default="manual",
    ),
    StageName.VIDEO_GENERATION.value: StageContract(
        stage_name=StageName.VIDEO_GENERATION.value,
        runtime_handler="run_video_generation",
        produces=("video_bundle", "variant_assets.video"),
        required_inputs=("video_scripts",),
        optional_inputs=("storyboards", "creative_specs"),
        required_capabilities=("video_generation",),
        review_focus=("video completion", "segment stitch readiness", "provider task status"),
        success_criteria=("video assets are submitted or completed with traceable provider task state",),
        human_approval_default="manual",
    ),
    StageName.VISUAL_QUALITY_ASSESSMENT.value: StageContract(
        stage_name=StageName.VISUAL_QUALITY_ASSESSMENT.value,
        runtime_handler="run_visual_quality_assessment",
        produces=("visual_quality_report", "variant_scores.visual_quality"),
        required_inputs=("variants",),
        optional_inputs=("intake", "copy_images", "video_scripts", "storyboards", "videos", "social_review_contract"),
        required_capabilities=("text_generation", "image_understanding", "video_understanding"),
        review_focus=("product truth", "visual quality", "platform readiness", "regeneration gates"),
        success_criteria=("creative assets are scored and unsafe or low-quality variants are blocked before evaluation",),
        human_approval_default="manual",
    ),
    StageName.EVALUATION_SELECTION.value: StageContract(
        stage_name=StageName.EVALUATION_SELECTION.value,
        runtime_handler="run_evaluation_selection",
        produces=("winner_selection", "scorecard", "conversion_forecast"),
        required_inputs=("variants", "visual_quality"),
        optional_inputs=("copy_images", "video_scripts", "videos", "creative_specs", "gm_policy"),
        required_capabilities=("text_generation", "image_understanding", "video_understanding"),
        review_focus=("winner rationale", "score quality", "forecast assumptions"),
        success_criteria=("winner variant and scorecard are available for deliverables and downstream learning",),
        human_approval_default="manual",
    ),
}


def get_stage_contract(stage_name: str) -> StageContract:
    try:
        return STAGE_CONTRACTS[stage_name]
    except KeyError as exc:
        raise KeyError(f"unknown stage contract: {stage_name}") from exc


def stage_contracts_for_plan(pipeline_mode: str | None) -> list[StageContract]:
    return [get_stage_contract(stage_name) for stage_name in stage_plan_for(pipeline_mode)]


def all_stage_contracts() -> tuple[StageContract, ...]:
    return tuple(STAGE_CONTRACTS[stage] for stage in sorted(STAGE_CONTRACTS))

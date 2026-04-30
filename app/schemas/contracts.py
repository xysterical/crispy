from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class StageName(StrEnum):
    INTAKE = "intake"
    PLANNING = "planning"
    DIVERGENCE = "divergence"
    COPY_IMAGE_GENERATION = "copy_image_generation"
    VIDEO_SCRIPTING = "video_scripting"
    STORYBOARD_IMAGE_GENERATION = "storyboard_image_generation"
    VIDEO_GENERATION = "video_generation"
    VISUAL_QUALITY_ASSESSMENT = "visual_quality_assessment"
    EVALUATION_SELECTION = "evaluation_selection"


class Evidence(BaseModel):
    source: str
    summary: str
    url: str


class ResearchReport(BaseModel):
    market_insights: list[str] = Field(default_factory=list)
    audience_segments: list[str] = Field(default_factory=list)
    competitor_observations: list[str] = Field(default_factory=list)
    pain_points: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    tone_guidance: str = ""
    evidence: list[Evidence] = Field(default_factory=list)


class HookItem(BaseModel):
    angle: str
    hook: str
    target_emotion: str


class CreativeHypothesis(BaseModel):
    hypothesis_id: str
    message: str
    rationale: str


class CreativeBlueprint(BaseModel):
    audience_priority: list[str] = Field(default_factory=list)
    hook_matrix: list[HookItem] = Field(default_factory=list)
    hypotheses: list[CreativeHypothesis] = Field(default_factory=list)
    variant_plan: list[str] = Field(default_factory=list)
    narrative_constraints: list[str] = Field(default_factory=list)
    default_variant_count: int = 8


class CopyVariant(BaseModel):
    variant_id: str
    primary_text: str
    headline: str
    description: str
    call_to_action: str


class ImageAssetRef(BaseModel):
    variant_id: str
    uri: str
    aspect_ratio: str = "1:1"
    prompt: str


class VideoPlan(BaseModel):
    hook: str
    script: str
    storyboard: list[str] = Field(default_factory=list)
    shot_list: list[str] = Field(default_factory=list)
    localization_notes: list[str] = Field(default_factory=list)
    output_ratio: str = "9:16"


class CreativeBundle(BaseModel):
    copy_variants: list[CopyVariant] = Field(default_factory=list)
    image_assets: list[ImageAssetRef] = Field(default_factory=list)
    video_plan: VideoPlan
    video_sample_uri: str


class ScoreBreakdown(BaseModel):
    attraction: float = Field(ge=0, le=100)
    clarity: float = Field(ge=0, le=100)
    brand_alignment: float = Field(ge=0, le=100)
    compliance: float = Field(ge=0, le=100)
    ai_naturalness: float = Field(ge=0, le=100)


class ComplianceLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ScoreCard(BaseModel):
    sub_scores: ScoreBreakdown
    total_score: float = Field(ge=0, le=100)
    risk_labels: list[str] = Field(default_factory=list)
    explanation: dict[str, str] = Field(default_factory=dict)
    compliance_level: ComplianceLevel = ComplianceLevel.LOW
    ai_artifact_score: float = Field(ge=0, le=100)


class ConversionForecast(BaseModel):
    score_0_100: float = Field(ge=0, le=100)
    confidence_0_1: float = Field(ge=0, le=1)
    drivers: list[str] = Field(default_factory=list)
    recommended_action: str


class StageEnvelope(BaseModel):
    stage: StageName
    payload: dict


class FeedbackRow(BaseModel):
    project_name: str
    creative_key: str
    variant_id: str | None = None
    campaign_name: str | None = None
    run_id: str | None = None
    impressions: int = 0
    clicks: int = 0
    spend: float = 0
    conversions: int = 0
    revenue: float = 0
    period_start: date | None = None
    period_end: date | None = None
    platform: str | None = None
    platform_campaign_id: str | None = None

    @field_validator("impressions", "clicks", "conversions")
    @classmethod
    def non_negative_int(cls, value: int) -> int:
        if value < 0:
            raise ValueError("metric cannot be negative")
        return value

    @field_validator("spend", "revenue")
    @classmethod
    def non_negative_float(cls, value: float) -> float:
        if value < 0:
            raise ValueError("metric cannot be negative")
        return value


class ProductVisualIdentity(BaseModel):
    product_type: str = ""
    category_tags: list[str] = Field(default_factory=list)
    colors: list[str] = Field(default_factory=list)
    materials: list[str] = Field(default_factory=list)
    visible_text_logo: list[str] = Field(default_factory=list)
    must_preserve_details: list[str] = Field(default_factory=list)
    missing_fact_warnings: list[str] = Field(default_factory=list)
    best_reference_images: list[str] = Field(default_factory=list)
    best_reference_frames: list[str] = Field(default_factory=list)
    source_media_count: dict = Field(default_factory=dict)
    raw_media_summary: str = ""


class ProductIntake(BaseModel):
    product_name: str
    market: str = "US"
    locale: str = "en-US"
    category_tags: list[str] = Field(default_factory=list)
    business_context: dict = Field(default_factory=dict)
    manual_research_brief: str = ""
    url_references: list[str] = Field(default_factory=list)
    sku_summary: list[dict] = Field(default_factory=list)
    image_references: list[dict] = Field(default_factory=list)
    video_references: list[dict] = Field(default_factory=list)
    asset_media_summary: str = ""
    visual_identity: ProductVisualIdentity = Field(default_factory=ProductVisualIdentity)


class PlanningBrief(BaseModel):
    strategic_angles: list[str] = Field(default_factory=list)
    audience_priorities: list[str] = Field(default_factory=list)
    positioning: str = ""
    constraints: list[str] = Field(default_factory=list)
    gm_lessons: list[dict] = Field(default_factory=list)


class VariantCandidate(BaseModel):
    variant_id: str
    angle: str
    hook: str
    message: str
    rationale: str = ""


class VariantSet(BaseModel):
    variants: list[VariantCandidate] = Field(default_factory=list)


class CopyImageBundle(BaseModel):
    copy_variants: list[CopyVariant] = Field(default_factory=list)
    image_assets: list[ImageAssetRef] = Field(default_factory=list)


class TikTokShotTiming(BaseModel):
    start: float = 0.0
    end: float = 0.0
    visual: str = ""
    text_overlay: str = ""
    intent: str = "product_demo"


class TikTokScriptDetails(BaseModel):
    style: str = "ugc_demo"
    opening_hook: str = ""
    on_screen_text: list[str] = Field(default_factory=list)
    voiceover_lines: list[str] = Field(default_factory=list)
    shot_timing: list[TikTokShotTiming] = Field(default_factory=list)
    product_proof_points: list[str] = Field(default_factory=list)
    cta: str = ""
    compliance_notes: list[str] = Field(default_factory=list)


class VideoScriptItem(BaseModel):
    variant_id: str
    hook: str
    script: str
    shot_list: list[str] = Field(default_factory=list)
    tiktok: TikTokScriptDetails | None = None


class VideoScriptPack(BaseModel):
    scripts: list[VideoScriptItem] = Field(default_factory=list)


class StoryboardFrame(BaseModel):
    variant_id: str
    frame_id: str
    prompt: str
    image_uri: str


class StoryboardPack(BaseModel):
    frames: list[StoryboardFrame] = Field(default_factory=list)


class VideoAsset(BaseModel):
    variant_id: str
    video_uri: str
    duration_seconds: float = 0.0


class VideoBundle(BaseModel):
    videos: list[VideoAsset] = Field(default_factory=list)


class RankedVariant(BaseModel):
    variant_id: str
    total_score: float = Field(ge=0, le=100)
    sub_scores: dict[str, float] = Field(default_factory=dict)
    compliance_level: ComplianceLevel = ComplianceLevel.LOW
    reasons: list[str] = Field(default_factory=list)
    compliance_risks: list[str] = Field(default_factory=list)
    compliance_reasons: list[str] = Field(default_factory=list)
    recommended_action: str = "manual_review"


class EvaluationResult(BaseModel):
    ranked_variants: list[RankedVariant] = Field(default_factory=list)
    top_k: list[RankedVariant] = Field(default_factory=list)
    winner: RankedVariant | None = None
    scorecard: ScoreCard
    forecast: ConversionForecast


class SelectedDeliverables(BaseModel):
    winner_variant_id: str
    copy_variant: CopyVariant | None = None
    image_assets: list[ImageAssetRef] = Field(default_factory=list)
    video_asset: VideoAsset | None = None
    reasoning: list[str] = Field(default_factory=list)


class GmMemoryEntry(BaseModel):
    project_id: str
    category_tags: list[str] = Field(default_factory=list)
    winners: list[dict] = Field(default_factory=list)
    failures: list[dict] = Field(default_factory=list)
    summary: str = ""


class GmInstructionVersion(BaseModel):
    project_id: str
    version: int
    content: dict = Field(default_factory=dict)
    source_feedback_import_id: str | None = None

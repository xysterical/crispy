from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class StageName(StrEnum):
    RESEARCH = "research"
    IDEATION = "ideation"
    GENERATION = "generation"
    SCORING = "scoring"


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
    campaign_name: str | None = None
    run_id: str | None = None
    impressions: int = 0
    clicks: int = 0
    spend: float = 0
    conversions: int = 0
    revenue: float = 0
    period_start: date | None = None
    period_end: date | None = None

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

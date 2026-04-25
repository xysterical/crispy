from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.contracts import ConversionForecast, FeedbackRow, ScoreCard, StageName

PipelineMode = Literal["copy_image_only", "video_only", "full_multimodal"]


class RunCreateRequest(BaseModel):
    workspace_name: str
    project_name: str
    product_name: str
    product_code: str
    industry_code: str
    campaign_name: str
    channel: str = "meta"
    objective: str = "conversions"
    market: str = "US"
    locale: str = "en-US"
    creative_preset: str
    creative_specs: dict = Field(default_factory=dict)
    variant_count: int = 8
    context: dict = Field(default_factory=dict)
    model_provider: str | None = "openai"
    model_name: str | None = "gpt-4.1"
    pipeline_mode: PipelineMode = "full_multimodal"
    enable_research: bool = False
    manual_research_brief: str = ""
    business_context: dict = Field(default_factory=dict)
    category_tags: list[str] = Field(default_factory=list)


class StageTaskView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    stage_name: str
    status: str
    attempt: int
    review_notes: str | None = None
    output_payload: dict = Field(default_factory=dict)
    metadata_json: dict = Field(default_factory=dict)
    summary: str = ""
    raw_ref: str = ""
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class RunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    current_stage: str | None
    workspace_id: str
    project_id: str
    product_id: str
    product_code: str
    industry_code: str
    campaign_id: str
    market: str
    locale: str
    model_provider: str | None
    model_name: str | None
    creative_preset: str
    creative_specs: dict = Field(default_factory=dict)
    pipeline_mode: PipelineMode = "full_multimodal"
    enable_research: bool = False
    manual_research_brief: str = ""
    business_context: dict = Field(default_factory=dict)
    category_tags: list[str] = Field(default_factory=list)
    budget_used: float
    variant_count: int
    created_at: datetime
    updated_at: datetime
    stage_tasks: list[StageTaskView] = Field(default_factory=list)
    variant_summary: dict = Field(default_factory=dict)
    latest_scorecard: ScoreCard | None = None
    latest_forecast: ConversionForecast | None = None


class RunSummary(BaseModel):
    id: str
    status: str
    current_stage: str | None
    pipeline_mode: PipelineMode = "full_multimodal"
    project_id: str
    product_code: str = ""
    industry_code: str = ""
    updated_at: datetime


class ReviewActionRequest(BaseModel):
    notes: str = ""


class FeedbackImportResponse(BaseModel):
    import_id: str
    rows: int
    snapshots_created: int
    memory_entry_id: str | None = None


class LeaderboardItem(BaseModel):
    creative_key: str
    weighted_score: float
    ctr: float
    cpc: float
    cpa: float
    roas: float
    recommendation: str


class LeaderboardResponse(BaseModel):
    project_id: str
    ranking: list[LeaderboardItem]


class PersonaView(BaseModel):
    agent_name: str
    display_name: str | None = None
    stage: str | None = None
    role: str | None = None
    content: str
    version: int
    source_path: str


class PersonaPatchRequest(BaseModel):
    content: str
    changed_by: str = "dashboard"


class PipelineStageResult(BaseModel):
    stage: StageName
    payload: dict


class FeedbackImportRequest(BaseModel):
    workspace_name: str
    project_name: str
    rows: list[FeedbackRow]
    file_name: str = "manual_import.csv"


class VariantReviewRequest(BaseModel):
    action: Literal[
        "approve_variant",
        "reject_variant",
        "shortlist_variant",
        "set_winner",
        "request_regeneration",
    ]
    comment: str = ""
    tags: list[str] = Field(default_factory=list)


class VariantSelectRequest(BaseModel):
    shortlist: bool = False
    winner: bool = False
    comment: str = ""


class VariantRegenerateRequest(BaseModel):
    reason: str
    target_stage: str | None = None


class PersonaMeta(BaseModel):
    agent_name: str
    display_name: str
    stage: str
    role: str
    order: int
    source_path: str


class AgentApiConfigView(BaseModel):
    agent_name: str
    provider_name: str
    model_name: str
    api_base_url: str | None = None
    api_key_env: str | None = None
    api_key_available: bool = False
    image_provider_name: str | None = None
    image_model_name: str | None = None
    image_api_base_url: str | None = None
    image_api_key_env: str | None = None
    image_api_key_available: bool = False
    video_provider_name: str | None = None
    video_model_name: str | None = None
    video_api_base_url: str | None = None
    video_api_key_env: str | None = None
    video_api_key_available: bool = False
    thinking_mode: Literal["auto", "enabled", "disabled"] = "auto"
    thinking_budget_tokens: int | None = None
    max_output_tokens: int | None = None
    request_timeout_seconds: int | None = None
    thinking_applied: bool = False
    extra: dict = Field(default_factory=dict)
    is_default: bool = False
    updated_at: datetime


class AgentApiConfigPatchRequest(BaseModel):
    provider_name: str | None = None
    model_name: str | None = None
    api_base_url: str | None = None
    api_key_env: str | None = None
    image_provider_name: str | None = None
    image_model_name: str | None = None
    image_api_base_url: str | None = None
    image_api_key_env: str | None = None
    video_provider_name: str | None = None
    video_model_name: str | None = None
    video_api_base_url: str | None = None
    video_api_key_env: str | None = None
    thinking_mode: Literal["auto", "enabled", "disabled"] | None = None
    thinking_budget_tokens: int | None = None
    max_output_tokens: int | None = None
    request_timeout_seconds: int | None = None
    extra: dict | None = None


class DeliverablesResponse(BaseModel):
    run_id: str
    winner_variant_id: str | None = None
    deliverables: dict = Field(default_factory=dict)
    score: dict = Field(default_factory=dict)


class VariantAssetView(BaseModel):
    id: str
    stage_name: str
    asset_type: str
    uri: str | None = None
    provider_name: str | None = None
    model_name: str | None = None
    prompt_summary: str | None = None
    failure_category: str | None = None
    error_message: str | None = None
    payload: dict = Field(default_factory=dict)
    created_at: datetime


class VariantReviewView(BaseModel):
    id: str
    action: str
    comment: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata_json: dict = Field(default_factory=dict)
    created_at: datetime


class VariantScoreView(BaseModel):
    id: str
    stage_name: str
    score_type: str
    total_score: float | None = None
    compliance_level: str | None = None
    recommended_action: str | None = None
    sub_scores: dict = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    forecast: dict = Field(default_factory=dict)
    payload: dict = Field(default_factory=dict)
    created_at: datetime


class RunVariantView(BaseModel):
    id: str
    run_id: str
    variant_id: str
    angle: str = ""
    hook: str = ""
    message: str = ""
    status: str
    current_score: float | None = None
    is_winner: bool = False
    shortlisted: bool = False
    review_status: str | None = None
    regenerate_requested: bool = False
    metadata_json: dict = Field(default_factory=dict)
    strategy_brief: dict = Field(default_factory=dict)
    assets: list[VariantAssetView] = Field(default_factory=list)
    scores: list[VariantScoreView] = Field(default_factory=list)
    reviews: list[VariantReviewView] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class VariantsResponse(BaseModel):
    run_id: str
    variants: list[dict] = Field(default_factory=list)
    ranked: list[dict] = Field(default_factory=list)
    items: list[RunVariantView] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)


class PipelineModeView(BaseModel):
    mode: PipelineMode
    display_name: str
    stages: list[str] = Field(default_factory=list)
    agents: list[str] = Field(default_factory=list)
    agent_count: int = 0


class DataSourceInfo(BaseModel):
    id: str
    name: str
    path: str
    url: str
    is_active: bool = False


class DataSourceListResponse(BaseModel):
    active_url: str
    items: list[DataSourceInfo] = Field(default_factory=list)


class DataSourceSelectRequest(BaseModel):
    url: str


class ArtifactListItem(BaseModel):
    artifact_id: str
    run_id: str
    artifact_type: str
    stage_name: str
    pipeline_mode: PipelineMode | str
    product_code: str = ""
    uri: str
    preview_text: str = ""
    score: float | None = None
    created_at: datetime


class ArtifactListResponse(BaseModel):
    page: int
    page_size: int
    total: int
    items: list[ArtifactListItem] = Field(default_factory=list)


class GmMemoryItem(BaseModel):
    id: str
    project_id: str
    run_id: str | None = None
    memory_scope: str
    product_code: str | None = None
    industry_code: str | None = None
    source_type: str
    score_hint: float | None = None
    content: dict = Field(default_factory=dict)
    created_at: datetime


class RunPreflightRequest(BaseModel):
    pipeline_mode: PipelineMode = "full_multimodal"
    has_image_inputs: bool = False
    has_video_inputs: bool = False


class CapabilityCheckItem(BaseModel):
    key: str
    severity: Literal["ok", "warn", "error"]
    message: str
    stage_name: str | None = None
    agent_name: str | None = None


class RunPreflightResponse(BaseModel):
    ok: bool = True
    severity: Literal["ok", "warn", "error"] = "ok"
    summary: str = ""
    checks: list[CapabilityCheckItem] = Field(default_factory=list)

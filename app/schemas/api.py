from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.contracts import ConversionForecast, FeedbackRow, ScoreCard, StageName


class RunCreateRequest(BaseModel):
    workspace_name: str
    project_name: str
    product_name: str
    campaign_name: str
    channel: str = "meta"
    objective: str = "conversions"
    market: str = "US"
    locale: str = "en-US"
    variant_count: int = 8
    context: dict = Field(default_factory=dict)
    model_provider: str = "kimi"
    model_name: str = "kimi-default-text"


class StageTaskView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    stage_name: str
    status: str
    attempt: int
    review_notes: str | None = None
    output_payload: dict = Field(default_factory=dict)
    metadata_json: dict = Field(default_factory=dict)
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
    campaign_id: str
    market: str
    locale: str
    model_provider: str
    model_name: str
    budget_used: float
    variant_count: int
    created_at: datetime
    updated_at: datetime
    stage_tasks: list[StageTaskView] = Field(default_factory=list)
    latest_scorecard: ScoreCard | None = None
    latest_forecast: ConversionForecast | None = None


class RunSummary(BaseModel):
    id: str
    status: str
    current_stage: str | None
    project_id: str
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
    extra: dict = Field(default_factory=dict)
    is_default: bool = False
    updated_at: datetime


class AgentApiConfigPatchRequest(BaseModel):
    provider_name: str | None = None
    model_name: str | None = None
    api_base_url: str | None = None
    api_key_env: str | None = None
    extra: dict | None = None

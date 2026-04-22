from __future__ import annotations

import uuid
from datetime import UTC, datetime, date
from enum import StrEnum

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.data.base import Base, json_type


def utcnow() -> datetime:
    return datetime.now(UTC)


class StageName(StrEnum):
    RESEARCH = "research"
    IDEATION = "ideation"
    GENERATION = "generation"
    SCORING = "scoring"


class RunStatus(StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    WAITING_REVIEW = "waiting_review"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class TaskStatus(StrEnum):
    DRAFT = "draft"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_REVIEW = "waiting_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"


class Workspace(Base):
    __tablename__ = "workspace"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    config: Mapped[dict] = mapped_column(json_type(), default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    projects: Mapped[list["Project"]] = relationship(back_populates="workspace")


class Project(Base):
    __tablename__ = "project"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_project_workspace_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    market: Mapped[str] = mapped_column(String(16), default="US")
    locale: Mapped[str] = mapped_column(String(16), default="en-US")
    metric_weights: Mapped[dict] = mapped_column(
        json_type(),
        default=lambda: {"ctr": 0.35, "cpc": 0.15, "cpa": 0.30, "roas": 0.20},
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    workspace: Mapped[Workspace] = relationship(back_populates="projects")
    products: Mapped[list["Product"]] = relationship(back_populates="project")
    campaigns: Mapped[list["Campaign"]] = relationship(back_populates="project")
    runs: Mapped[list["PipelineRun"]] = relationship(back_populates="project")


class Product(Base):
    __tablename__ = "product"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_product_project_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(json_type(), default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="products")
    campaigns: Mapped[list["Campaign"]] = relationship(back_populates="product")
    runs: Mapped[list["PipelineRun"]] = relationship(back_populates="product")


class Campaign(Base):
    __tablename__ = "campaign"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_campaign_project_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), nullable=False)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("product.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), default="meta")
    objective: Mapped[str] = mapped_column(String(64), default="conversions")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="campaigns")
    product: Mapped[Product | None] = relationship(back_populates="campaigns")
    runs: Mapped[list["PipelineRun"]] = relationship(back_populates="campaign")


class PipelineRun(Base):
    __tablename__ = "pipeline_run"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"), nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), nullable=False)
    product_id: Mapped[str] = mapped_column(ForeignKey("product.id"), nullable=False)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaign.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=RunStatus.DRAFT.value)
    current_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    market: Mapped[str] = mapped_column(String(16), default="US")
    locale: Mapped[str] = mapped_column(String(16), default="en-US")
    model_provider: Mapped[str] = mapped_column(String(64), default="kimi")
    model_name: Mapped[str] = mapped_column(String(128), default="kimi-default-text")
    budget_used: Mapped[float] = mapped_column(Float, default=0.0)
    variant_count: Mapped[int] = mapped_column(Integer, default=8)
    context_json: Mapped[dict] = mapped_column(json_type(), default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    project: Mapped[Project] = relationship(back_populates="runs")
    product: Mapped[Product] = relationship(back_populates="runs")
    campaign: Mapped[Campaign] = relationship(back_populates="runs")
    stage_tasks: Mapped[list["StageTask"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    artifacts: Mapped[list["Artifact"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    scorecards: Mapped[list["ScoreCard"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class StageTask(Base):
    __tablename__ = "stage_task"
    __table_args__ = (UniqueConstraint("run_id", "stage_name", name="uq_stage_task_run_stage"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(ForeignKey("pipeline_run.id"), nullable=False)
    stage_name: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=TaskStatus.DRAFT.value)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    input_payload: Mapped[dict] = mapped_column(json_type(), default=dict)
    output_payload: Mapped[dict] = mapped_column(json_type(), default=dict)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(json_type(), default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[PipelineRun] = relationship(back_populates="stage_tasks")
    scorecards: Mapped[list["ScoreCard"]] = relationship(back_populates="stage_task")


class Artifact(Base):
    __tablename__ = "artifact"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(ForeignKey("pipeline_run.id"), nullable=False)
    stage_name: Mapped[str] = mapped_column(String(32), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(32), nullable=False)
    uri: Mapped[str] = mapped_column(String(512), nullable=False)
    payload: Mapped[dict] = mapped_column(json_type(), default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[PipelineRun] = relationship(back_populates="artifacts")


class ScoreCard(Base):
    __tablename__ = "scorecard"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(ForeignKey("pipeline_run.id"), nullable=False)
    stage_task_id: Mapped[str] = mapped_column(ForeignKey("stage_task.id"), nullable=False)
    total_score: Mapped[float] = mapped_column(Float, nullable=False)
    sub_scores: Mapped[dict] = mapped_column(json_type(), default=dict)
    risk_labels: Mapped[list[str]] = mapped_column(json_type(), default=list)
    explanation: Mapped[dict] = mapped_column(json_type(), default=dict)
    compliance_level: Mapped[str] = mapped_column(String(16), default="low")
    ai_artifact_score: Mapped[float] = mapped_column(Float, default=0.0)
    forecast: Mapped[dict] = mapped_column(json_type(), default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[PipelineRun] = relationship(back_populates="scorecards")
    stage_task: Mapped[StageTask] = relationship(back_populates="scorecards")


class FeedbackImport(Base):
    __tablename__ = "feedback_import"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"), nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), nullable=False)
    file_name: Mapped[str] = mapped_column(String(256), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    raw_rows: Mapped[list[dict]] = mapped_column(json_type(), default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PerformanceSnapshot(Base):
    __tablename__ = "performance_snapshot"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), nullable=False)
    campaign_id: Mapped[str | None] = mapped_column(ForeignKey("campaign.id"), nullable=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("pipeline_run.id"), nullable=True)
    creative_key: Mapped[str] = mapped_column(String(128), nullable=False)
    metrics: Mapped[dict] = mapped_column(json_type(), default=dict)
    weighted_score: Mapped[float] = mapped_column(Float, default=0.0)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PersonaVersion(Base):
    __tablename__ = "persona_version"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_path: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[str] = mapped_column(String(64), default="dashboard")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GmMemory(Base):
    __tablename__ = "gm_memory"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("project.id"), nullable=False)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("pipeline_run.id"), nullable=True)
    memory_type: Mapped[str] = mapped_column(String(32), default="strategy")
    content: Mapped[dict] = mapped_column(json_type(), default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


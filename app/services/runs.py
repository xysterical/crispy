from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.registry import stage_agent
from app.agents.runtime import AgentsRuntime
from app.data.models import (
    Artifact,
    Campaign,
    PipelineRun,
    Product,
    Project,
    RunStatus,
    ScoreCard as ScoreCardModel,
    StageTask,
    TaskStatus,
    Workspace,
)
from app.orchestrator.state_machine import STAGE_ORDER, next_stage
from app.schemas.api import RunCreateRequest
from app.schemas.contracts import ComplianceLevel, CreativeBlueprint, CreativeBundle, ResearchReport
from app.services.agent_api_configs import resolve_agent_config


runtime = AgentsRuntime()


def utcnow() -> datetime:
    return datetime.now(UTC)


def _get_or_create_workspace(db: Session, name: str) -> Workspace:
    workspace = db.scalar(select(Workspace).where(Workspace.name == name))
    if workspace:
        return workspace
    workspace = Workspace(name=name)
    db.add(workspace)
    db.flush()
    return workspace


def _get_or_create_project(db: Session, workspace_id: str, name: str, market: str, locale: str) -> Project:
    project = db.scalar(
        select(Project).where(Project.workspace_id == workspace_id, Project.name == name)
    )
    if project:
        if market:
            project.market = market
        if locale:
            project.locale = locale
        return project
    project = Project(workspace_id=workspace_id, name=name, market=market, locale=locale)
    db.add(project)
    db.flush()
    return project


def _get_or_create_product(db: Session, project_id: str, name: str) -> Product:
    product = db.scalar(select(Product).where(Product.project_id == project_id, Product.name == name))
    if product:
        return product
    product = Product(project_id=project_id, name=name)
    db.add(product)
    db.flush()
    return product


def _get_or_create_campaign(
    db: Session,
    project_id: str,
    product_id: str,
    name: str,
    channel: str,
    objective: str,
) -> Campaign:
    campaign = db.scalar(select(Campaign).where(Campaign.project_id == project_id, Campaign.name == name))
    if campaign:
        campaign.product_id = product_id
        campaign.channel = channel
        campaign.objective = objective
        return campaign
    campaign = Campaign(
        project_id=project_id,
        product_id=product_id,
        name=name,
        channel=channel,
        objective=objective,
    )
    db.add(campaign)
    db.flush()
    return campaign


def create_run(db: Session, payload: RunCreateRequest) -> PipelineRun:
    workspace = _get_or_create_workspace(db, payload.workspace_name)
    project = _get_or_create_project(db, workspace.id, payload.project_name, payload.market, payload.locale)
    product = _get_or_create_product(db, project.id, payload.product_name)
    campaign = _get_or_create_campaign(
        db,
        project_id=project.id,
        product_id=product.id,
        name=payload.campaign_name,
        channel=payload.channel,
        objective=payload.objective,
    )

    run = PipelineRun(
        workspace_id=workspace.id,
        project_id=project.id,
        product_id=product.id,
        campaign_id=campaign.id,
        status=RunStatus.RUNNING.value,
        current_stage=STAGE_ORDER[0],
        market=payload.market,
        locale=payload.locale,
        model_provider=payload.model_provider,
        model_name=payload.model_name,
        variant_count=payload.variant_count,
        context_json=payload.context,
    )
    db.add(run)
    db.flush()

    for stage_name in STAGE_ORDER:
        task_status = TaskStatus.QUEUED.value if stage_name == STAGE_ORDER[0] else TaskStatus.DRAFT.value
        task = StageTask(
            run_id=run.id,
            stage_name=stage_name,
            status=task_status,
            input_payload={},
        )
        db.add(task)
    db.flush()
    return run


def get_run(db: Session, run_id: str) -> PipelineRun:
    run = db.get(PipelineRun, run_id)
    if not run:
        raise ValueError(f"run not found: {run_id}")
    return run


def get_stage_task(db: Session, run_id: str, stage_name: str) -> StageTask:
    task = db.scalar(
        select(StageTask).where(StageTask.run_id == run_id, StageTask.stage_name == stage_name)
    )
    if not task:
        raise ValueError(f"stage task not found: {run_id}/{stage_name}")
    return task


def latest_scorecard(db: Session, run_id: str) -> ScoreCardModel | None:
    return db.scalar(
        select(ScoreCardModel)
        .where(ScoreCardModel.run_id == run_id)
        .order_by(ScoreCardModel.created_at.desc())
    )


def approve_stage(db: Session, run_id: str, notes: str = "") -> PipelineRun:
    run = get_run(db, run_id)
    if not run.current_stage:
        return run
    task = get_stage_task(db, run_id, run.current_stage)
    if task.status != TaskStatus.WAITING_REVIEW.value:
        raise ValueError(f"stage {run.current_stage} is not waiting for review")
    task.status = TaskStatus.APPROVED.value
    task.approved_at = utcnow()
    task.review_notes = notes

    nxt = next_stage(run.current_stage)
    if nxt is None:
        run.current_stage = None
        run.status = RunStatus.COMPLETED.value
    else:
        next_task = get_stage_task(db, run_id, nxt)
        next_task.status = TaskStatus.QUEUED.value
        run.current_stage = nxt
        run.status = RunStatus.RUNNING.value
    run.updated_at = utcnow()
    db.flush()
    return run


def reject_stage(db: Session, run_id: str, notes: str = "") -> PipelineRun:
    run = get_run(db, run_id)
    if not run.current_stage:
        raise ValueError("run already completed")
    task = get_stage_task(db, run_id, run.current_stage)
    if task.status not in {TaskStatus.WAITING_REVIEW.value, TaskStatus.FAILED.value}:
        raise ValueError(f"stage {run.current_stage} is not rejectable")
    task.status = TaskStatus.REJECTED.value
    task.rejected_at = utcnow()
    task.review_notes = notes
    task.metadata_json = {**task.metadata_json, "human_feedback": notes}

    # Requeue same stage for another generation attempt.
    task.status = TaskStatus.QUEUED.value
    run.status = RunStatus.RUNNING.value
    run.updated_at = utcnow()
    db.flush()
    return run


def _stage_output(db: Session, run_id: str, stage_name: str) -> dict:
    task = get_stage_task(db, run_id, stage_name)
    return task.output_payload or {}


def _build_task_input(db: Session, run: PipelineRun, task: StageTask) -> dict:
    base = {
        "context": run.context_json or {},
        "market": run.market,
        "locale": run.locale,
        "variant_count": run.variant_count,
    }
    if task.stage_name == "research":
        return base
    if task.stage_name == "ideation":
        return {"research": _stage_output(db, run.id, "research"), **base}
    if task.stage_name == "generation":
        return {"blueprint": _stage_output(db, run.id, "ideation"), **base}
    if task.stage_name == "scoring":
        return {"bundle": _stage_output(db, run.id, "generation"), **base}
    return base


def execute_next_queued_stage(db: Session) -> StageTask | None:
    task = db.scalar(select(StageTask).where(StageTask.status == TaskStatus.QUEUED.value).limit(1))
    if not task:
        return None
    run = get_run(db, task.run_id)
    task.status = TaskStatus.RUNNING.value
    task.started_at = utcnow()
    task.attempt += 1
    task.input_payload = _build_task_input(db, run, task)
    run.status = RunStatus.RUNNING.value
    run.current_stage = task.stage_name
    run.updated_at = utcnow()
    db.flush()

    try:
        agent_name = stage_agent(task.stage_name)
        resolved = resolve_agent_config(
            db,
            agent_name=agent_name,
            run_provider=run.model_provider,
            run_model=run.model_name,
        )
        provider_name = resolved["provider_name"]
        model_name = resolved["model_name"]
        task.metadata_json = {**(task.metadata_json or {}), "agent_name": agent_name, "resolved_api": resolved}

        output = None
        if task.stage_name == "research":
            output = runtime.run_research(
                run.id,
                task.input_payload,
                provider=provider_name,
                model=model_name,
            )
        elif task.stage_name == "ideation":
            research = ResearchReport.model_validate(task.input_payload["research"])
            output = runtime.run_ideation(
                run.id,
                research,
                variant_count=run.variant_count,
                provider=provider_name,
                model=model_name,
            )
        elif task.stage_name == "generation":
            blueprint = CreativeBlueprint.model_validate(task.input_payload["blueprint"])
            output = runtime.run_generation(
                run.id,
                blueprint,
                provider=provider_name,
                model=model_name,
            )
        elif task.stage_name == "scoring":
            bundle = CreativeBundle.model_validate(task.input_payload["bundle"])
            output = runtime.run_scoring(
                run.id,
                bundle,
                provider=provider_name,
                model=model_name,
            )
        else:
            raise ValueError(f"unknown stage: {task.stage_name}")

        task.output_payload = output.payload
        task.model_used = output.model_used
        task.completed_at = utcnow()
        run.budget_used = float(run.budget_used or 0.0) + output.estimated_cost
        run.updated_at = utcnow()

        for artifact in output.artifacts:
            db.add(
                Artifact(
                    run_id=run.id,
                    stage_name=task.stage_name,
                    artifact_type=artifact["type"],
                    uri=artifact["uri"],
                    payload=artifact["payload"],
                )
            )

        if task.stage_name == "scoring" and output.scorecard and output.forecast:
            scorecard = output.scorecard
            db.add(
                ScoreCardModel(
                    run_id=run.id,
                    stage_task_id=task.id,
                    total_score=scorecard.total_score,
                    sub_scores=scorecard.sub_scores.model_dump(),
                    risk_labels=scorecard.risk_labels,
                    explanation=scorecard.explanation,
                    compliance_level=scorecard.compliance_level.value,
                    ai_artifact_score=scorecard.ai_artifact_score,
                    forecast=output.forecast.model_dump(),
                )
            )
            if scorecard.compliance_level == ComplianceLevel.HIGH:
                task.status = TaskStatus.REJECTED.value
                task.review_notes = "Auto blocked: high legal/compliance risk."
                run.status = RunStatus.REJECTED.value
            else:
                task.status = TaskStatus.WAITING_REVIEW.value
                run.status = RunStatus.WAITING_REVIEW.value
        else:
            task.status = TaskStatus.WAITING_REVIEW.value
            run.status = RunStatus.WAITING_REVIEW.value
        db.flush()
        return task
    except Exception as exc:  # pragma: no cover - defensive path
        task.status = TaskStatus.FAILED.value
        task.error_message = str(exc)
        task.completed_at = utcnow()
        run.status = RunStatus.FAILED.value
        run.updated_at = utcnow()
        db.flush()
        return task

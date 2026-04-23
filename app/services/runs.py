from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.agents.registry import stage_agent
from app.agents.runtime import AgentsRuntime
from app.data.models import (
    Artifact,
    Campaign,
    GmMemory,
    PipelineRun,
    Product,
    Project,
    RunStatus,
    ScoreCard as ScoreCardModel,
    StageTask,
    TaskStatus,
    Workspace,
)
from app.orchestrator.state_machine import next_stage, stage_plan_for
from app.schemas.api import RunCreateRequest
from app.schemas.contracts import (
    CopyImageBundle,
    PlanningBrief,
    ProductIntake,
    VariantSet,
    VideoBundle,
    VideoScriptPack,
)
from app.services.agent_api_configs import resolve_agent_config, resolve_agent_runtime


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
    project = db.scalar(select(Project).where(Project.workspace_id == workspace_id, Project.name == name))
    if project:
        project.market = market
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
    stage_plan = stage_plan_for(payload.pipeline_mode)
    workspace = _get_or_create_workspace(db, payload.workspace_name)
    project = _get_or_create_project(db, workspace.id, payload.project_name, payload.market, payload.locale)
    product = _get_or_create_product(db, project.id, payload.product_name)
    campaign = _get_or_create_campaign(
        db=db,
        project_id=project.id,
        product_id=product.id,
        name=payload.campaign_name,
        channel=payload.channel,
        objective=payload.objective,
    )
    context_json = payload.context or {}
    context_json.setdefault("business_context", payload.business_context or {})
    context_json.setdefault("category_tags", payload.category_tags or [])
    run = PipelineRun(
        workspace_id=workspace.id,
        project_id=project.id,
        product_id=product.id,
        campaign_id=campaign.id,
        status=RunStatus.RUNNING.value,
        current_stage=stage_plan[0],
        market=payload.market,
        locale=payload.locale,
        pipeline_mode=payload.pipeline_mode,
        model_provider=payload.model_provider,
        model_name=payload.model_name,
        variant_count=payload.variant_count,
        enable_research=payload.enable_research,
        manual_research_brief=payload.manual_research_brief,
        business_context=payload.business_context or {},
        category_tags=payload.category_tags or [],
        context_json=context_json,
    )
    db.add(run)
    db.flush()

    for idx, stage_name in enumerate(stage_plan):
        task_status = TaskStatus.QUEUED.value if idx == 0 else TaskStatus.DRAFT.value
        db.add(
            StageTask(
                run_id=run.id,
                stage_name=stage_name,
                status=task_status,
                input_payload={},
            )
        )
    db.flush()
    return run


def get_run(db: Session, run_id: str) -> PipelineRun:
    run = db.get(PipelineRun, run_id)
    if not run:
        raise ValueError(f"run not found: {run_id}")
    return run


def get_stage_task(db: Session, run_id: str, stage_name: str) -> StageTask:
    task = db.scalar(select(StageTask).where(StageTask.run_id == run_id, StageTask.stage_name == stage_name))
    if not task:
        raise ValueError(f"stage task not found: {run_id}/{stage_name}")
    return task


def latest_scorecard(db: Session, run_id: str) -> ScoreCardModel | None:
    return db.scalar(select(ScoreCardModel).where(ScoreCardModel.run_id == run_id).order_by(desc(ScoreCardModel.created_at)))


def _requeue_next_stage(db: Session, run_id: str, stage_name: str | None) -> None:
    if not stage_name:
        return
    next_task = get_stage_task(db, run_id, stage_name)
    if next_task.status in {TaskStatus.DRAFT.value, TaskStatus.REJECTED.value, TaskStatus.FAILED.value}:
        next_task.status = TaskStatus.QUEUED.value


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

    nxt = next_stage(run.current_stage, run.pipeline_mode)
    if nxt is None:
        run.current_stage = None
        run.status = RunStatus.COMPLETED.value
    else:
        _requeue_next_stage(db, run.id, nxt)
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
    task.status = TaskStatus.QUEUED.value
    task.rejected_at = utcnow()
    task.review_notes = notes
    task.metadata_json = {**(task.metadata_json or {}), "human_feedback": notes}
    run.status = RunStatus.RUNNING.value
    run.updated_at = utcnow()
    db.flush()
    return run


def _stage_output_optional(db: Session, run_id: str, stage_name: str) -> dict:
    task = db.scalar(select(StageTask).where(StageTask.run_id == run_id, StageTask.stage_name == stage_name))
    if not task:
        return {}
    return task.output_payload or {}


def _recent_gm_lessons(db: Session, run: PipelineRun, limit: int = 5) -> list[dict]:
    rows = db.scalars(
        select(GmMemory).where(GmMemory.project_id == run.project_id).order_by(desc(GmMemory.created_at)).limit(20)
    ).all()
    if not run.category_tags:
        return [row.content for row in rows[:limit]]
    tag_set = set(run.category_tags)
    matched: list[dict] = []
    for row in rows:
        tags = set(row.content.get("category_tags", []))
        if not tags or tags.intersection(tag_set):
            matched.append(row.content)
        if len(matched) >= limit:
            break
    return matched


def _build_task_input(db: Session, run: PipelineRun, task: StageTask) -> dict:
    product = db.get(Product, run.product_id)
    base = {
        "run_id": run.id,
        "product_name": product.name if product else "unknown_product",
        "context": run.context_json or {},
        "market": run.market,
        "locale": run.locale,
        "pipeline_mode": run.pipeline_mode,
        "variant_count": run.variant_count,
        "enable_research": run.enable_research,
        "manual_research_brief": run.manual_research_brief or "",
        "business_context": run.business_context or {},
        "category_tags": run.category_tags or [],
    }
    if task.stage_name == "intake":
        return base
    if task.stage_name == "planning":
        return {**base, "intake": _stage_output_optional(db, run.id, "intake"), "gm_lessons": _recent_gm_lessons(db, run)}
    if task.stage_name == "divergence":
        return {**base, "planning": _stage_output_optional(db, run.id, "planning")}
    if task.stage_name == "copy_image_generation":
        return {
            **base,
            "variants": _stage_output_optional(db, run.id, "divergence"),
            "intake": _stage_output_optional(db, run.id, "intake"),
        }
    if task.stage_name == "video_scripting":
        return {**base, "variants": _stage_output_optional(db, run.id, "divergence")}
    if task.stage_name == "storyboard_image_generation":
        return {**base, "video_scripts": _stage_output_optional(db, run.id, "video_scripting")}
    if task.stage_name == "video_generation":
        return {**base, "video_scripts": _stage_output_optional(db, run.id, "video_scripting")}
    if task.stage_name == "evaluation_selection":
        return {
            **base,
            "variants": _stage_output_optional(db, run.id, "divergence"),
            "copy_images": _stage_output_optional(db, run.id, "copy_image_generation"),
            "video_scripts": _stage_output_optional(db, run.id, "video_scripting"),
            "videos": _stage_output_optional(db, run.id, "video_generation"),
        }
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
        runtime_config = resolve_agent_runtime(resolved)
        provider_name = resolved["provider_name"]
        model_name = resolved["model_name"]
        task.metadata_json = {**(task.metadata_json or {}), "agent_name": agent_name, "resolved_api": resolved}

        output = None
        if task.stage_name == "intake":
            output = runtime.run_intake(run.id, task.input_payload, provider=provider_name, model=model_name, runtime_config=runtime_config)
        elif task.stage_name == "planning":
            intake = ProductIntake.model_validate(task.input_payload["intake"])
            output = runtime.run_planning(
                run.id,
                intake,
                gm_lessons=task.input_payload.get("gm_lessons", []),
                enable_research=bool(task.input_payload.get("enable_research")),
                provider=provider_name,
                model=model_name,
                runtime_config=runtime_config,
            )
        elif task.stage_name == "divergence":
            planning = PlanningBrief.model_validate(task.input_payload["planning"])
            output = runtime.run_divergence(
                run.id,
                planning,
                variant_count=run.variant_count,
                provider=provider_name,
                model=model_name,
                runtime_config=runtime_config,
            )
        elif task.stage_name == "copy_image_generation":
            variants = VariantSet.model_validate(task.input_payload["variants"])
            intake_payload = task.input_payload.get("intake") or {}
            intake = ProductIntake.model_validate(intake_payload) if intake_payload else None
            output = runtime.run_copy_image_generation(
                run.id,
                variants,
                intake=intake,
                business_context=task.input_payload.get("business_context", {}),
                market=run.market,
                locale=run.locale,
                provider=provider_name,
                model=model_name,
                runtime_config=runtime_config,
            )
        elif task.stage_name == "video_scripting":
            variants = VariantSet.model_validate(task.input_payload["variants"])
            output = runtime.run_video_scripting(
                run.id,
                variants,
                provider=provider_name,
                model=model_name,
                runtime_config=runtime_config,
            )
        elif task.stage_name == "storyboard_image_generation":
            scripts = VideoScriptPack.model_validate(task.input_payload["video_scripts"])
            output = runtime.run_storyboard_image_generation(
                run.id,
                scripts,
                provider=provider_name,
                model=model_name,
                runtime_config=runtime_config,
            )
        elif task.stage_name == "video_generation":
            scripts = VideoScriptPack.model_validate(task.input_payload["video_scripts"])
            output = runtime.run_video_generation(
                run.id,
                scripts,
                provider=provider_name,
                model=model_name,
                runtime_config=runtime_config,
            )
        elif task.stage_name == "evaluation_selection":
            variants = VariantSet.model_validate(task.input_payload["variants"])
            copy_bundle = CopyImageBundle.model_validate(task.input_payload.get("copy_images", {}))
            script_pack = VideoScriptPack.model_validate(task.input_payload.get("video_scripts", {}))
            video_bundle = VideoBundle.model_validate(task.input_payload.get("videos", {}))
            output = runtime.run_evaluation_selection(
                run.id,
                variants,
                copy_bundle,
                script_pack,
                video_bundle,
                provider=provider_name,
                model=model_name,
                runtime_config=runtime_config,
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

        if task.stage_name == "evaluation_selection" and output.scorecard and output.forecast:
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

        task.status = TaskStatus.WAITING_REVIEW.value
        run.status = RunStatus.WAITING_REVIEW.value
        db.flush()
        return task
    except Exception as exc:  # pragma: no cover
        task.status = TaskStatus.FAILED.value
        task.error_message = str(exc)
        task.completed_at = utcnow()
        run.status = RunStatus.FAILED.value
        run.updated_at = utcnow()
        db.flush()
        return task


def run_deliverables(db: Session, run_id: str) -> dict:
    eval_task = get_stage_task(db, run_id, "evaluation_selection")
    payload = eval_task.output_payload or {}
    return payload.get("selected_deliverables", {})


def run_variants(db: Session, run_id: str) -> dict:
    divergence = get_stage_task(db, run_id, "divergence")
    evaluation = get_stage_task(db, run_id, "evaluation_selection")
    return {
        "variants": (divergence.output_payload or {}).get("variants", []),
        "ranked": ((evaluation.output_payload or {}).get("evaluation_result", {}) or {}).get("ranked_variants", []),
    }

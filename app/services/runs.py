from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.agents.registry import STAGE_CONTRACT_VERSION, stage_agent, stage_collaborators
from app.agents.runtime import AgentsRuntime
from app.data.models import (
    Artifact,
    Campaign,
    GmMemory,
    PipelineRun,
    Product,
    Project,
    RunStatus,
    RunVariant,
    ScoreCard as ScoreCardModel,
    StageTask,
    TaskFailureCategory,
    TaskStatus,
    VariantAsset,
    VariantLifecycleStatus,
    VariantReview,
    VariantReviewAction,
    VariantScore,
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
from app.services.creative_specs import resolve_creative_specs
from app.services.personas import get_persona


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


def _get_or_create_product(db: Session, project_id: str, name: str, product_code: str) -> Product:
    normalized_code = product_code.strip()
    if not normalized_code:
        raise ValueError("product_code is required")
    product = db.scalar(select(Product).where(Product.product_code == normalized_code))
    if product:
        if product.name != name:
            raise ValueError(f"product_code conflict: {normalized_code} is already bound to product_name={product.name}")
        if product.project_id != project_id:
            raise ValueError(f"product_code conflict: {normalized_code} belongs to another project")
        return product
    product = Product(project_id=project_id, name=name, product_code=normalized_code)
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


def _model_snapshot_for_run(db: Session, *, run_provider: str | None, run_model: str | None) -> dict:
    fallback_provider = run_provider or "openai"
    fallback_model = run_model or "gpt-4.1"
    agent_names = ("planning_agent", "copy_image_agent", "video_generation_agent", "evaluation_agent")
    snapshot = {}
    default_cfg = resolve_agent_config(
        db,
        agent_name="default",
        run_provider=fallback_provider,
        run_model=fallback_model,
    )
    snapshot["default_text"] = {
        "provider_name": default_cfg.get("provider_name"),
        "model_name": default_cfg.get("model_name"),
        "api_base_url": default_cfg.get("api_base_url"),
        "api_key_env": default_cfg.get("api_key_env"),
    }
    for agent_name in agent_names:
        cfg = resolve_agent_config(
            db,
            agent_name=agent_name,
            run_provider=fallback_provider,
            run_model=fallback_model,
        )
        snapshot[agent_name] = {
            "provider_name": cfg.get("provider_name"),
            "model_name": cfg.get("model_name"),
            "api_base_url": cfg.get("api_base_url"),
            "api_key_env": cfg.get("api_key_env"),
        }
    return snapshot


def create_run(db: Session, payload: RunCreateRequest) -> PipelineRun:
    stage_plan = stage_plan_for(payload.pipeline_mode)
    workspace = _get_or_create_workspace(db, payload.workspace_name)
    project = _get_or_create_project(db, workspace.id, payload.project_name, payload.market, payload.locale)
    product = _get_or_create_product(db, project.id, payload.product_name, payload.product_code)
    campaign = _get_or_create_campaign(
        db=db,
        project_id=project.id,
        product_id=product.id,
        name=payload.campaign_name,
        channel=payload.channel,
        objective=payload.objective,
    )
    creative_specs = resolve_creative_specs(payload.creative_preset, payload.creative_specs)
    model_snapshot = _model_snapshot_for_run(
        db,
        run_provider=payload.model_provider,
        run_model=payload.model_name,
    )
    context_json = payload.context or {}
    context_json.setdefault("business_context", payload.business_context or {})
    context_json.setdefault("category_tags", payload.category_tags or [])
    context_json["creative_specs"] = creative_specs
    context_json["model_snapshot"] = model_snapshot
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
        product_code=product.product_code,
        industry_code=payload.industry_code,
        creative_preset=payload.creative_preset,
        creative_specs=creative_specs,
        model_provider=payload.model_provider or "openai",
        model_name=payload.model_name or "gpt-4.1",
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


def get_run_variant(db: Session, run_id: str, variant_id: str) -> RunVariant:
    row = db.scalar(select(RunVariant).where(RunVariant.run_id == run_id, RunVariant.variant_id == variant_id))
    if not row:
        raise ValueError(f"run variant not found: {run_id}/{variant_id}")
    return row


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
    task.failure_category = None

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
    task.failure_category = TaskFailureCategory.HUMAN_REJECT.value
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
    product_rows = db.scalars(
        select(GmMemory)
        .where(
            GmMemory.project_id == run.project_id,
            GmMemory.memory_scope == "product",
            GmMemory.product_code == run.product_code,
        )
        .order_by(desc(GmMemory.score_hint), desc(GmMemory.created_at))
        .limit(10)
    ).all()
    industry_rows = db.scalars(
        select(GmMemory)
        .where(
            GmMemory.project_id == run.project_id,
            GmMemory.memory_scope == "industry",
            GmMemory.industry_code == run.industry_code,
        )
        .order_by(desc(GmMemory.score_hint), desc(GmMemory.created_at))
        .limit(10)
    ).all()

    merged: list[dict] = []
    seen_fingerprints: set[str] = set()
    for row in [*product_rows[:5], *industry_rows[:3]]:
        payload = {
            "memory_scope": row.memory_scope,
            "product_code": row.product_code,
            "industry_code": row.industry_code,
            "source_type": row.source_type,
            "score_hint": row.score_hint,
            "content": row.content or {},
        }
        fingerprint = f"{payload['memory_scope']}|{payload['product_code']}|{payload['industry_code']}|{json.dumps(payload['content'], sort_keys=True)}"
        if fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(fingerprint)
        merged.append(payload)
        if len(merged) >= limit:
            break
    return merged


def _build_task_input(db: Session, run: PipelineRun, task: StageTask) -> dict:
    product = db.get(Product, run.product_id)
    base = {
        "run_id": run.id,
        "product_name": product.name if product else "unknown_product",
        "context": run.context_json or {},
        "market": run.market,
        "locale": run.locale,
        "product_code": run.product_code,
        "industry_code": run.industry_code,
        "pipeline_mode": run.pipeline_mode,
        "creative_preset": run.creative_preset,
        "creative_specs": run.creative_specs or {},
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
        return {
            **base,
            "variants": _stage_output_optional(db, run.id, "divergence"),
            "intake": _stage_output_optional(db, run.id, "intake"),
        }
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


def _persona_snapshots(db: Session, agent_names: list[str]) -> dict:
    snapshots: dict = {}
    for agent_name in agent_names:
        content, version, source_path = get_persona(db, agent_name)
        snapshots[agent_name] = {
            "version": version,
            "source_path": source_path,
            "content": content,
        }
    return snapshots


def _classify_failure(exc: Exception) -> str:
    message = str(exc).lower()
    if "timeout" in message:
        return TaskFailureCategory.TIMEOUT.value
    if "compliance" in message and "block" in message:
        return TaskFailureCategory.COMPLIANCE_BLOCK.value
    if "validation" in message or "pydantic" in message or "schema" in message:
        return TaskFailureCategory.SCHEMA_ERROR.value
    if "provider" in message or "request failed" in message or "endpoint" in message or "api" in message:
        return TaskFailureCategory.PROVIDER_ERROR.value
    return TaskFailureCategory.UNKNOWN.value


def _variant_idempotency_key(stage_name: str, asset_type: str, variant_id: str, discriminator: str = "") -> str:
    base = f"{stage_name}:{asset_type}:{variant_id}"
    if discriminator:
        return f"{base}:{discriminator}"
    return base


def _uri_has_payload(uri: str | None, min_bytes: int = 1024) -> bool:
    if not uri:
        return False
    path = Path(uri)
    return path.exists() and path.is_file() and path.stat().st_size > min_bytes


def _generated_asset_failure(payload: dict, uri: str | None) -> tuple[str | None, str | None]:
    error = payload.get("error")
    if error:
        return TaskFailureCategory.PROVIDER_ERROR.value, str(error)
    status = str(payload.get("generation_status") or "").lower()
    if status in {"failed", "cancelled", "canceled"}:
        return TaskFailureCategory.PROVIDER_ERROR.value, f"provider task status={status}"
    source = str(payload.get("source") or "").lower()
    if source == "placeholder":
        return TaskFailureCategory.PROVIDER_ERROR.value, "provider returned placeholder media"
    if source == "external_task_pending":
        return None, None
    if uri and not _uri_has_payload(uri):
        return TaskFailureCategory.PROVIDER_ERROR.value, "generated media file is empty or placeholder-sized"
    return None, None


def _upsert_run_variant(
    db: Session,
    *,
    run_id: str,
    variant_id: str,
    angle: str,
    hook: str,
    message: str,
    rationale: str = "",
    status: str | None = None,
) -> RunVariant:
    row = db.scalar(select(RunVariant).where(RunVariant.run_id == run_id, RunVariant.variant_id == variant_id))
    now = utcnow()
    if not row:
        row = RunVariant(
            run_id=run_id,
            variant_id=variant_id,
            angle=angle,
            hook=hook,
            message=message,
            status=status or VariantLifecycleStatus.DRAFT.value,
            metadata_json={"strategy_brief": {"angle": angle, "hook": hook, "message": message, "rationale": rationale}},
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        db.flush()
        return row
    row.angle = angle
    row.hook = hook
    row.message = message
    row.updated_at = now
    row.metadata_json = {
        **(row.metadata_json or {}),
        "strategy_brief": {"angle": angle, "hook": hook, "message": message, "rationale": rationale},
    }
    if status:
        row.status = status
    return row


def _upsert_variant_asset(
    db: Session,
    *,
    variant: RunVariant,
    run_id: str,
    stage_name: str,
    asset_type: str,
    uri: str | None,
    provider_name: str | None,
    model_name: str | None,
    prompt_summary: str | None,
    payload: dict,
    idempotency_key: str,
    failure_category: str | None = None,
    error_message: str | None = None,
) -> VariantAsset:
    row = db.scalar(
        select(VariantAsset).where(
            VariantAsset.run_variant_id == variant.id,
            VariantAsset.idempotency_key == idempotency_key,
        )
    )
    if not row:
        row = VariantAsset(
            run_variant_id=variant.id,
            run_id=run_id,
            stage_name=stage_name,
            asset_type=asset_type,
            uri=uri,
            provider_name=provider_name,
            model_name=model_name,
            prompt_summary=prompt_summary,
            failure_category=failure_category,
            error_message=error_message,
            idempotency_key=idempotency_key,
            payload=payload,
        )
        db.add(row)
        db.flush()
        return row
    row.uri = uri
    row.provider_name = provider_name
    row.model_name = model_name
    row.prompt_summary = prompt_summary
    row.failure_category = failure_category
    row.error_message = error_message
    row.payload = payload
    return row


def _upsert_variant_score(
    db: Session,
    *,
    variant: RunVariant,
    run_id: str,
    stage_name: str,
    score_type: str,
    total_score: float | None,
    compliance_level: str | None,
    recommended_action: str | None,
    sub_scores: dict,
    reasons: list[str],
    forecast: dict,
    payload: dict,
) -> VariantScore:
    row = db.scalar(
        select(VariantScore).where(
            VariantScore.run_variant_id == variant.id,
            VariantScore.score_type == score_type,
        )
    )
    if not row:
        row = VariantScore(
            run_variant_id=variant.id,
            run_id=run_id,
            stage_name=stage_name,
            score_type=score_type,
            total_score=total_score,
            compliance_level=compliance_level,
            recommended_action=recommended_action,
            sub_scores=sub_scores,
            reasons=reasons,
            forecast=forecast,
            payload=payload,
        )
        db.add(row)
        db.flush()
        return row
    row.stage_name = stage_name
    row.total_score = total_score
    row.compliance_level = compliance_level
    row.recommended_action = recommended_action
    row.sub_scores = sub_scores
    row.reasons = reasons
    row.forecast = forecast
    row.payload = payload
    return row


def _variant_library_sync(db: Session, run: PipelineRun, task: StageTask, output_payload: dict) -> None:
    stage_name = task.stage_name
    if stage_name == "divergence":
        for item in output_payload.get("variants", []):
            _upsert_run_variant(
                db,
                run_id=run.id,
                variant_id=item.get("variant_id", ""),
                angle=item.get("angle", ""),
                hook=item.get("hook", ""),
                message=item.get("message", ""),
                rationale=item.get("rationale", ""),
                status=VariantLifecycleStatus.DRAFT.value,
            )
        return

    if stage_name == "copy_image_generation":
        copy_variants = {item.get("variant_id"): item for item in output_payload.get("copy_variants", [])}
        image_assets = [item for item in output_payload.get("image_assets", []) if item.get("variant_id")]
        for variant_id, copy_payload in copy_variants.items():
            variant = get_run_variant(db, run.id, variant_id)
            _upsert_variant_asset(
                db,
                variant=variant,
                run_id=run.id,
                stage_name=stage_name,
                asset_type="copy",
                uri=None,
                provider_name=task.metadata_json.get("resolved_api", {}).get("provider_name"),
                model_name=task.metadata_json.get("resolved_api", {}).get("model_name"),
                prompt_summary=(copy_payload.get("headline") or copy_payload.get("primary_text") or "")[:240],
                payload=copy_payload,
                idempotency_key=_variant_idempotency_key(stage_name, "copy", variant_id),
            )
            variant.status = VariantLifecycleStatus.GENERATED.value
        for image_payload in image_assets:
            variant = get_run_variant(db, run.id, image_payload["variant_id"])
            failure_category, error_message = _generated_asset_failure(image_payload, image_payload.get("uri"))
            _upsert_variant_asset(
                db,
                variant=variant,
                run_id=run.id,
                stage_name=stage_name,
                asset_type="image",
                uri=image_payload.get("uri"),
                provider_name=task.metadata_json.get("resolved_api", {}).get("image_provider_name"),
                model_name=task.metadata_json.get("resolved_api", {}).get("image_model_name"),
                prompt_summary=(image_payload.get("prompt") or "")[:240],
                payload=image_payload,
                idempotency_key=_variant_idempotency_key(stage_name, "image", image_payload["variant_id"]),
                failure_category=failure_category,
                error_message=error_message,
            )
        return

    if stage_name == "video_scripting":
        for script_payload in output_payload.get("scripts", []):
            variant = get_run_variant(db, run.id, script_payload.get("variant_id", ""))
            _upsert_variant_asset(
                db,
                variant=variant,
                run_id=run.id,
                stage_name=stage_name,
                asset_type="video_script",
                uri=None,
                provider_name=task.metadata_json.get("resolved_api", {}).get("provider_name"),
                model_name=task.metadata_json.get("resolved_api", {}).get("model_name"),
                prompt_summary=(script_payload.get("hook") or "")[:240],
                payload=script_payload,
                idempotency_key=_variant_idempotency_key(stage_name, "video_script", script_payload.get("variant_id", "")),
            )
            variant.status = VariantLifecycleStatus.GENERATED.value
        return

    if stage_name == "storyboard_image_generation":
        for frame_payload in output_payload.get("frames", []):
            variant = get_run_variant(db, run.id, frame_payload.get("variant_id", ""))
            failure_category = TaskFailureCategory.PROVIDER_ERROR.value if frame_payload.get("error") else None
            _upsert_variant_asset(
                db,
                variant=variant,
                run_id=run.id,
                stage_name=stage_name,
                asset_type="storyboard_frame",
                uri=frame_payload.get("image_uri"),
                provider_name=frame_payload.get("image_provider") or task.metadata_json.get("resolved_api", {}).get("provider_name"),
                model_name=frame_payload.get("image_model") or task.metadata_json.get("resolved_api", {}).get("model_name"),
                prompt_summary=(frame_payload.get("prompt") or "")[:240],
                payload=frame_payload,
                failure_category=failure_category,
                error_message=frame_payload.get("error"),
                idempotency_key=_variant_idempotency_key(
                    stage_name,
                    "storyboard_frame",
                    frame_payload.get("variant_id", ""),
                    frame_payload.get("frame_id", ""),
                ),
            )
        return

    if stage_name == "video_generation":
        for video_payload in output_payload.get("videos", []):
            variant = get_run_variant(db, run.id, video_payload.get("variant_id", ""))
            failure_category, error_message = _generated_asset_failure(video_payload, video_payload.get("video_uri"))
            _upsert_variant_asset(
                db,
                variant=variant,
                run_id=run.id,
                stage_name=stage_name,
                asset_type="video",
                uri=video_payload.get("video_uri"),
                provider_name=task.metadata_json.get("resolved_api", {}).get("video_provider_name"),
                model_name=task.metadata_json.get("resolved_api", {}).get("video_model_name"),
                prompt_summary=f"video asset for {video_payload.get('variant_id', '')}",
                payload=video_payload,
                idempotency_key=_variant_idempotency_key(stage_name, "video", video_payload.get("variant_id", "")),
                failure_category=failure_category,
                error_message=error_message,
            )
            variant.status = VariantLifecycleStatus.GENERATED.value
        return

    if stage_name == "evaluation_selection":
        evaluation = (output_payload.get("evaluation_result") or {})
        forecast = evaluation.get("forecast") or {}
        ranked = evaluation.get("ranked_variants") or []
        winner = ((output_payload.get("selected_deliverables") or {}).get("winner_variant_id")) or None
        manual_winner = db.scalar(
            select(RunVariant).where(
                RunVariant.run_id == run.id,
                RunVariant.is_winner.is_(True),
                RunVariant.review_status == "winner",
            )
        )
        if manual_winner:
            winner = manual_winner.variant_id
        for ranked_payload in ranked:
            variant = get_run_variant(db, run.id, ranked_payload.get("variant_id", ""))
            _upsert_variant_score(
                db,
                variant=variant,
                run_id=run.id,
                stage_name=stage_name,
                score_type="evaluation",
                total_score=ranked_payload.get("total_score"),
                compliance_level=ranked_payload.get("compliance_level"),
                recommended_action=ranked_payload.get("recommended_action"),
                sub_scores=ranked_payload.get("sub_scores") or {},
                reasons=ranked_payload.get("reasons") or [],
                forecast=forecast,
                payload=ranked_payload,
            )
            _upsert_variant_score(
                db,
                variant=variant,
                run_id=run.id,
                stage_name=stage_name,
                score_type="compliance",
                total_score=None,
                compliance_level=ranked_payload.get("compliance_level"),
                recommended_action=ranked_payload.get("recommended_action"),
                sub_scores={},
                reasons=ranked_payload.get("compliance_reasons") or [],
                forecast={},
                payload={
                    "risks": ranked_payload.get("compliance_risks") or [],
                    "reasons": ranked_payload.get("compliance_reasons") or [],
                },
            )
            variant.current_score = ranked_payload.get("total_score")
            variant.metadata_json = {
                **(variant.metadata_json or {}),
                "evaluation": ranked_payload,
            }
            variant.is_winner = variant.variant_id == winner
            variant.shortlisted = variant.variant_id in {item.get("variant_id") for item in evaluation.get("top_k", [])}
            variant.review_status = ranked_payload.get("recommended_action")
            variant.regenerate_requested = ranked_payload.get("recommended_action") == "iterate_new_variants"
            variant.status = (
                VariantLifecycleStatus.WINNER.value
                if variant.is_winner
                else VariantLifecycleStatus.SHORTLISTED.value
                if variant.shortlisted
                else variant.status
            )
        return


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
        lead_agent = stage_agent(task.stage_name)
        collaborators = list(stage_collaborators(task.stage_name))
        resolved = resolve_agent_config(
            db,
            agent_name=lead_agent,
            run_provider=run.model_provider,
            run_model=run.model_name,
        )
        runtime_config = resolve_agent_runtime(resolved)
        provider_name = resolved["provider_name"]
        model_name = resolved["model_name"]
        task.metadata_json = {
            **(task.metadata_json or {}),
            "agent_name": lead_agent,
            "collaborators": collaborators,
            "stage_contract_version": STAGE_CONTRACT_VERSION,
            "resolved_api": resolved,
            "persona_snapshots": _persona_snapshots(db, [lead_agent, *collaborators]),
        }

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
                creative_specs=task.input_payload.get("creative_specs", {}),
                market=run.market,
                locale=run.locale,
                provider=provider_name,
                model=model_name,
                runtime_config=runtime_config,
            )
        elif task.stage_name == "video_scripting":
            variants = VariantSet.model_validate(task.input_payload["variants"])
            intake_payload = task.input_payload.get("intake") or {}
            intake = ProductIntake.model_validate(intake_payload) if intake_payload else None
            output = runtime.run_video_scripting(
                run.id,
                variants,
                intake=intake,
                business_context=task.input_payload.get("business_context", {}),
                provider=provider_name,
                model=model_name,
                runtime_config=runtime_config,
            )
        elif task.stage_name == "storyboard_image_generation":
            scripts = VideoScriptPack.model_validate(task.input_payload["video_scripts"])
            storyboard_runtime_config = runtime_config
            if not ((storyboard_runtime_config.get("image") or {}).get("api_base_url")):
                image_resolved = resolve_agent_config(
                    db,
                    agent_name="copy_image_agent",
                    run_provider=run.model_provider,
                    run_model=run.model_name,
                )
                image_runtime = resolve_agent_runtime(image_resolved).get("image") or {}
                storyboard_runtime_config = {**runtime_config, "image": image_runtime}
                task.metadata_json = {
                    **(task.metadata_json or {}),
                    "storyboard_image_config_source": "copy_image_agent",
                }
            output = runtime.run_storyboard_image_generation(
                run.id,
                scripts,
                creative_specs=task.input_payload.get("creative_specs", {}),
                provider=provider_name,
                model=model_name,
                runtime_config=storyboard_runtime_config,
            )
        elif task.stage_name == "video_generation":
            scripts = VideoScriptPack.model_validate(task.input_payload["video_scripts"])
            def persist_video_asset(video_payload: dict) -> None:
                current_payload = task.output_payload or {"videos": []}
                current_videos = [
                    item for item in current_payload.get("videos", []) if item.get("variant_id") != video_payload.get("variant_id")
                ]
                current_videos.append(video_payload)
                task.output_payload = {"videos": current_videos}
                db.add(
                    Artifact(
                        run_id=run.id,
                        stage_name=task.stage_name,
                        artifact_type="generated_video",
                        uri=video_payload.get("video_uri"),
                        payload=video_payload,
                    )
                )
                _variant_library_sync(db, run, task, {"videos": [video_payload]})
                run.updated_at = utcnow()
                db.commit()

            output = runtime.run_video_generation(
                run.id,
                scripts,
                creative_specs=task.input_payload.get("creative_specs", {}),
                provider=provider_name,
                model=model_name,
                runtime_config=runtime_config,
                on_video_asset=persist_video_asset,
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
        task.failure_category = None
        task.error_message = None
        run.budget_used = float(run.budget_used or 0.0) + output.estimated_cost
        run.updated_at = utcnow()

        for artifact in output.artifacts:
            if task.stage_name == "video_generation" and artifact["type"] == "generated_video":
                continue
            db.add(
                Artifact(
                    run_id=run.id,
                    stage_name=task.stage_name,
                    artifact_type=artifact["type"],
                    uri=artifact["uri"],
                    payload=artifact["payload"],
                )
            )

        _variant_library_sync(db, run, task, output.payload)

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
        task.failure_category = _classify_failure(exc)
        task.completed_at = utcnow()
        run.status = RunStatus.FAILED.value
        run.updated_at = utcnow()
        db.flush()
        return task


def _variant_summary(db: Session, run_id: str) -> dict:
    rows = db.scalars(select(RunVariant).where(RunVariant.run_id == run_id)).all()
    counter = Counter(row.status for row in rows)
    return {
        "total": len(rows),
        "winner_count": sum(1 for row in rows if row.is_winner),
        "shortlisted_count": sum(1 for row in rows if row.shortlisted),
        "regeneration_requested_count": sum(1 for row in rows if row.regenerate_requested),
        "status_counts": dict(counter),
    }


def _serialize_run_variant(db: Session, row: RunVariant) -> dict:
    assets = db.scalars(select(VariantAsset).where(VariantAsset.run_variant_id == row.id).order_by(VariantAsset.created_at.asc())).all()
    reviews = db.scalars(select(VariantReview).where(VariantReview.run_variant_id == row.id).order_by(VariantReview.created_at.asc())).all()
    scores = db.scalars(select(VariantScore).where(VariantScore.run_variant_id == row.id).order_by(VariantScore.created_at.asc())).all()
    return {
        "id": row.id,
        "run_id": row.run_id,
        "variant_id": row.variant_id,
        "angle": row.angle,
        "hook": row.hook,
        "message": row.message,
        "status": row.status,
        "current_score": row.current_score,
        "is_winner": row.is_winner,
        "shortlisted": row.shortlisted,
        "review_status": row.review_status,
        "regenerate_requested": row.regenerate_requested,
        "metadata_json": row.metadata_json or {},
        "strategy_brief": (row.metadata_json or {}).get("strategy_brief", {}),
        "assets": [
            {
                "id": asset.id,
                "stage_name": asset.stage_name,
                "asset_type": asset.asset_type,
                "uri": asset.uri,
                "provider_name": asset.provider_name,
                "model_name": asset.model_name,
                "prompt_summary": asset.prompt_summary,
                "failure_category": asset.failure_category,
                "error_message": asset.error_message,
                "payload": asset.payload or {},
                "created_at": asset.created_at,
            }
            for asset in assets
        ],
        "scores": [
            {
                "id": score.id,
                "stage_name": score.stage_name,
                "score_type": score.score_type,
                "total_score": score.total_score,
                "compliance_level": score.compliance_level,
                "recommended_action": score.recommended_action,
                "sub_scores": score.sub_scores or {},
                "reasons": score.reasons or [],
                "forecast": score.forecast or {},
                "payload": score.payload or {},
                "created_at": score.created_at,
            }
            for score in scores
        ],
        "reviews": [
            {
                "id": review.id,
                "action": review.action,
                "comment": review.comment,
                "tags": review.tags or [],
                "metadata_json": review.metadata_json or {},
                "created_at": review.created_at,
            }
            for review in reviews
        ],
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def run_deliverables(db: Session, run_id: str) -> dict:
    winner = db.scalar(
        select(RunVariant)
        .where(RunVariant.run_id == run_id, RunVariant.is_winner.is_(True))
        .order_by(desc(RunVariant.updated_at))
        .limit(1)
    )
    if not winner:
        eval_task = get_stage_task(db, run_id, "evaluation_selection")
        payload = eval_task.output_payload or {}
        return payload.get("selected_deliverables", {})
    assets = db.scalars(select(VariantAsset).where(VariantAsset.run_variant_id == winner.id).order_by(VariantAsset.created_at.asc())).all()
    scores = db.scalars(select(VariantScore).where(VariantScore.run_variant_id == winner.id)).all()
    copy_asset = next((item for item in assets if item.asset_type == "copy"), None)
    image_assets = [item.payload for item in assets if item.asset_type == "image"]
    video_asset = next((item.payload for item in assets if item.asset_type == "video"), None)
    evaluation = next((item for item in scores if item.score_type == "evaluation"), None)
    return {
        "winner_variant_id": winner.variant_id,
        "copy_variant": (copy_asset.payload if copy_asset else None),
        "image_assets": image_assets,
        "video_asset": video_asset,
        "reasoning": evaluation.reasons if evaluation else [],
    }


def run_variants(db: Session, run_id: str) -> dict:
    rows = db.scalars(select(RunVariant).where(RunVariant.run_id == run_id).order_by(RunVariant.variant_id.asc())).all()
    evaluation = get_stage_task(db, run_id, "evaluation_selection")
    ranked = ((evaluation.output_payload or {}).get("evaluation_result", {}) or {}).get("ranked_variants", [])
    return {
        "variants": [
            {
                "variant_id": row.variant_id,
                "angle": row.angle,
                "hook": row.hook,
                "message": row.message,
                "status": row.status,
            }
            for row in rows
        ],
        "ranked": ranked,
        "items": [_serialize_run_variant(db, row) for row in rows],
        "summary": _variant_summary(db, run_id),
    }


def refresh_video_task_assets(db: Session, run_id: str) -> dict:
    run = get_run(db, run_id)
    config = resolve_agent_config(
        db,
        agent_name="video_generation_agent",
        run_provider=run.model_provider,
        run_model=run.model_name,
    )
    runtime_config = resolve_agent_runtime(config)
    video_runtime = runtime_config.get("video") or {}
    provider_name = video_runtime.get("provider_name") or config.get("video_provider_name") or config.get("provider_name")
    model_name = video_runtime.get("model_name") or config.get("video_model_name") or config.get("model_name")
    provider = runtime.providers.get(provider_name)
    refreshed = 0
    completed = 0
    assets = db.scalars(
        select(VariantAsset).where(
            VariantAsset.run_id == run_id,
            VariantAsset.asset_type == "video",
        )
    ).all()
    for asset in assets:
        payload = dict(asset.payload or {})
        task_id = payload.get("external_task_id")
        status = str(payload.get("generation_status") or "").lower()
        if not task_id or status in {"completed", "succeeded", "success"}:
            continue
        result = provider.poll_video_task(
            task_id=task_id,
            model=model_name,
            api_base_url=video_runtime.get("api_base_url") or runtime_config.get("api_base_url"),
            api_key=video_runtime.get("api_key") or runtime_config.get("api_key"),
            extra=video_runtime.get("extra") or runtime_config.get("extra"),
        )
        selected = result.videos[0] if result.videos else None
        refreshed += 1
        payload["generation_status"] = result.status or (selected.status if selected else None) or payload.get("generation_status")
        payload["raw_response"] = result.raw_response or (selected.raw_response if selected else {}) or payload.get("raw_response") or {}
        if selected and selected.url:
            payload["result_url"] = selected.url
        if selected and (selected.url or selected.b64_data):
            video_bytes, source = runtime._materialize_generated_video(selected)
            if video_bytes:
                filename = f"{payload.get('variant_id') or asset.variant.variant_id}_sample.mp4"
                uri = runtime.media.write_binary_artifact(run_id, filename, video_bytes)
                payload["video_uri"] = uri
                payload["source"] = source
                payload["generation_status"] = "completed"
                asset.uri = uri
                completed += 1
        failure_category, error_message = _generated_asset_failure(payload, payload.get("video_uri"))
        asset.payload = payload
        asset.failure_category = failure_category
        asset.error_message = error_message
    db.flush()
    return {"refreshed": refreshed, "completed": completed, "summary": _variant_summary(db, run_id)}


def review_variant(
    db: Session,
    *,
    run_id: str,
    variant_id: str,
    action: str,
    comment: str = "",
    tags: list[str] | None = None,
    metadata: dict | None = None,
) -> RunVariant:
    variant = get_run_variant(db, run_id, variant_id)
    tags = tags or []
    metadata = metadata or {}
    if action == VariantReviewAction.APPROVE.value:
        variant.status = VariantLifecycleStatus.WINNER.value if variant.is_winner else VariantLifecycleStatus.APPROVED.value
        variant.review_status = "approved"
        variant.regenerate_requested = False
    elif action == VariantReviewAction.REJECT.value:
        variant.status = VariantLifecycleStatus.REJECTED.value
        variant.review_status = "rejected"
    elif action == VariantReviewAction.SHORTLIST.value:
        variant.status = VariantLifecycleStatus.SHORTLISTED.value
        variant.shortlisted = True
        variant.review_status = "shortlisted"
    elif action == VariantReviewAction.SET_WINNER.value:
        other_rows = db.scalars(select(RunVariant).where(RunVariant.run_id == run_id)).all()
        for row in other_rows:
            if row.id != variant.id and row.is_winner:
                row.is_winner = False
                if row.status == VariantLifecycleStatus.WINNER.value:
                    row.status = VariantLifecycleStatus.SHORTLISTED.value if row.shortlisted else VariantLifecycleStatus.GENERATED.value
        variant.is_winner = True
        variant.shortlisted = True
        variant.status = VariantLifecycleStatus.WINNER.value
        variant.review_status = "winner"
    elif action == VariantReviewAction.REQUEST_REGENERATION.value:
        variant.status = VariantLifecycleStatus.NEEDS_REGENERATION.value
        variant.regenerate_requested = True
        variant.review_status = "request_regeneration"
    else:
        raise ValueError(f"unsupported variant action: {action}")
    variant.updated_at = utcnow()
    db.add(
        VariantReview(
            run_variant_id=variant.id,
            run_id=run_id,
            action=action,
            comment=comment,
            tags=tags,
            metadata_json=metadata,
        )
    )
    db.flush()
    return variant

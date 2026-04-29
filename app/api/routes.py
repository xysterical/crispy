from __future__ import annotations

import io
import json
import uuid
import mimetypes
import asyncio
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from sqlalchemy import String, cast, desc, func, or_, select
from sqlalchemy.orm import Session

from app.agents.registry import stage_agent
from app.core.config import get_settings
from app.data.models import Artifact, GmMemory, PipelineRun, RunVariant, ScoreCard as ScoreCardModel, StageTask, VariantAsset
from app.data.session import (
    SessionLocal,
    get_active_database_url,
    get_db,
    list_local_sqlite_database_urls,
    switch_database_url,
)
from app.orchestrator.state_machine import PIPELINE_STAGE_PLANS, PipelineMode
from app.orchestrator.worker import worker
from app.schemas.api import (
    AgentApiConfigPatchRequest,
    AgentApiConfigView,
    AgentTraceEventView,
    ArtifactListItem,
    ArtifactListResponse,
    DataSourceInfo,
    DataSourceListResponse,
    DataSourceSelectRequest,
    DeliverablesResponse,
    FeedbackImportRequest,
    FeedbackImportResponse,
    GmMemoryItem,
    LeaderboardItem,
    LeaderboardResponse,
    PersonaMeta,
    PersonaPatchRequest,
    PersonaView,
    PipelineModeView,
    QueueHealthResponse,
    QueueRunningTask,
    QueueStatusResponse,
    ReviewActionRequest,
    RunCreateRequest,
    RunPreflightRequest,
    RunPreflightResponse,
    RunVariantView,
    RunSummary,
    RunView,
    StageTaskView,
    VariantRegenerateRequest,
    VariantReviewRequest,
    VariantSelectRequest,
    VariantsResponse,
    CreativePresetCreate,
    CreativePresetListResponse,
    CreativePresetUpdate,
    CreativePresetView,
    ProductConfigHint,
    RunTemplateCreate,
    RunTemplateUpdate,
    RunTemplateView,
    ShopAnalysisRequest,
    ShopAnalysisResponse,
    ShopAnalysisListItem,
    ShopAnalysisHistoryResponse,
)
from app.schemas.contracts import ComplianceLevel, ConversionForecast, ScoreCard
from app.services.agent_api_configs import (
    API_KEY_ENV_PREFIX,
    api_key_available,
    list_agent_configs,
    list_api_key_env_names,
    upsert_agent_config,
)
from app.services.feedback import import_feedback_rows, project_leaderboard
from app.services.intake_assets import process_uploaded_payloads
from app.services.marketplace_qa import is_marketplace_main_image
from app.services.personas import get_persona, list_persona_catalog, persona_info, update_persona
from app.services.creative_specs import (
    create_creative_preset,
    delete_creative_preset,
    get_creative_preset,
    list_system_presets,
    list_user_presets,
    update_creative_preset,
)
from app.services.capability_preflight import preflight_run_capabilities
from app.services.templates import (
    create_run_template,
    delete_run_template,
    get_run_template,
    list_run_templates,
    update_run_template,
)
from app.services.runs import (
    approve_stage,
    create_run,
    get_last_product_config,
    get_run,
    latest_scorecard,
    reject_stage,
    regenerate_variant_assets,
    refresh_async_assets,
    refresh_video_task_assets,
    review_variant,
    run_deliverables,
    run_trace_events,
    run_variants,
)
from app.services.shop_analysis import (
    list_shop_analyses,
    save_competitor_analysis,
    save_shop_profile,
)


router = APIRouter()
DEFAULT_GENERATED_ARTIFACT_TYPES = {
    "copy_image_bundle",
    "generated_image",
    "video_script_pack",
    "storyboard_pack",
    "storyboard_frame",
    "generated_video",
    "video_bundle",
    "visual_quality_report",
    "evaluation_selection",
}


def _load_json_list(raw: str | None, field_name: str) -> list:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"invalid json for {field_name}") from exc
    if not isinstance(parsed, list):
        raise HTTPException(status_code=400, detail=f"{field_name} must be a JSON list")
    return parsed


def _load_json_dict(raw: str | None, field_name: str) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"invalid json for {field_name}") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail=f"{field_name} must be a JSON object")
    return parsed


def _stage_task_summary(task: StageTask) -> str:
    payload = task.output_payload or {}
    if task.error_message:
        return f"error: {task.error_message[:160]}"
    if not payload:
        return "No output yet."
    if task.stage_name == "intake":
        return (
            f"Intake ready: sku={len(payload.get('sku_summary', []))}, "
            f"images={len(payload.get('image_references', []))}, videos={len(payload.get('video_references', []))}"
        )
    if task.stage_name == "planning":
        return (
            f"Planning brief: angles={len(payload.get('strategic_angles', []))}, "
            f"constraints={len(payload.get('constraints', []))}"
        )
    if task.stage_name == "divergence":
        return f"Variants generated: {len(payload.get('variants', []))}"
    if task.stage_name == "copy_image_generation":
        return (
            f"Copy/Image generated: copy_variants={len(payload.get('copy_variants', []))}, "
            f"image_assets={len(payload.get('image_assets', []))}"
        )
    if task.stage_name == "video_scripting":
        return f"Video scripts generated: {len(payload.get('scripts', []))}"
    if task.stage_name == "storyboard_image_generation":
        return f"Storyboard frames generated: {len(payload.get('frames', []))}"
    if task.stage_name == "video_generation":
        return f"Video assets generated: {len(payload.get('videos', []))}"
    if task.stage_name == "evaluation_selection":
        selected = payload.get("selected_deliverables", {}) or {}
        winner = selected.get("winner_variant_id") or "N/A"
        ranked = ((payload.get("evaluation_result", {}) or {}).get("ranked_variants", [])) or []
        return f"Evaluation complete: winner={winner}, ranked={len(ranked)}"
    keys = list(payload.keys())
    return f"Output keys: {', '.join(keys[:6])}"


def _resolve_media_path(path: str) -> Path:
    requested = Path(path).expanduser()
    if not requested.is_absolute():
        requested = (Path.cwd() / requested).resolve()
    settings_path = get_settings().assets_dir.resolve()
    try:
        requested.relative_to(settings_path)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="path outside allowed assets directory") from exc
    if not requested.exists() or not requested.is_file():
        raise HTTPException(status_code=404, detail="asset file not found")
    return requested


def _serialize_data_source(database_url: str, active_url: str) -> DataSourceInfo:
    path = database_url.removeprefix("sqlite:///")
    resolved = str(Path(path).expanduser().resolve()) if database_url.startswith("sqlite:///") else path
    return DataSourceInfo(
        id=database_url,
        name=Path(resolved).name if resolved else database_url,
        path=resolved,
        url=database_url,
        is_active=database_url == active_url,
    )


def _artifact_preview(payload: dict) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("headline", "primary_text", "description", "summary", "reasoning"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:180]
        if isinstance(value, list) and value:
            head = value[0]
            if isinstance(head, str) and head.strip():
                return head.strip()[:180]
    if "copy_variants" in payload and isinstance(payload["copy_variants"], list) and payload["copy_variants"]:
        item = payload["copy_variants"][0]
        if isinstance(item, dict):
            text = item.get("headline") or item.get("primary_text") or ""
            return str(text)[:180]
    return ""


def _parse_date_start(raw: str | None) -> datetime | None:
    if not raw:
        return None
    return datetime.fromisoformat(raw)


def _parse_date_end(raw: str | None) -> datetime | None:
    if not raw:
        return None
    return datetime.fromisoformat(raw) + timedelta(days=1)


def _serialize_run(db: Session, run: PipelineRun) -> RunView:
    tasks = db.scalars(select(StageTask).where(StageTask.run_id == run.id).order_by(StageTask.created_at.asc())).all()
    task_views = [
        StageTaskView(
            id=task.id,
            stage_name=task.stage_name,
            status=task.status,
            attempt=task.attempt,
            review_notes=task.review_notes,
            output_payload=task.output_payload or {},
            metadata_json=task.metadata_json or {},
            summary=_stage_task_summary(task),
            raw_ref=task.id,
            error_message=task.error_message,
            started_at=task.started_at,
            completed_at=task.completed_at,
        )
        for task in tasks
    ]

    scorecard_model = latest_scorecard(db, run.id)
    scorecard = None
    forecast = None
    if scorecard_model:
        scorecard = ScoreCard(
            sub_scores=scorecard_model.sub_scores,
            total_score=scorecard_model.total_score,
            risk_labels=scorecard_model.risk_labels,
            explanation=scorecard_model.explanation,
            compliance_level=ComplianceLevel(scorecard_model.compliance_level),
            ai_artifact_score=scorecard_model.ai_artifact_score,
        )
        forecast = ConversionForecast.model_validate(scorecard_model.forecast)
    trace_views = [
        AgentTraceEventView(
            id=event.id,
            run_id=event.run_id,
            stage_task_id=event.stage_task_id,
            stage_name=event.stage_name,
            agent_name=event.agent_name,
            event_type=event.event_type,
            visibility=event.visibility,
            message=event.message,
            provider_name=event.provider_name,
            model_name=event.model_name,
            payload=event.payload or {},
            created_at=event.created_at,
        )
        for event in run_trace_events(db, run.id, limit=200)
    ]

    return RunView(
        id=run.id,
        status=run.status,
        current_stage=run.current_stage,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        product_id=run.product_id,
        product_code=run.product_code,
        industry_code=run.industry_code,
        campaign_id=run.campaign_id,
        market=run.market,
        locale=run.locale,
        model_provider=run.model_provider,
        model_name=run.model_name,
        creative_preset=run.creative_preset,
        creative_specs=run.creative_specs or {},
        pipeline_mode=run.pipeline_mode,
        approval_mode=run.approval_mode or "manual",
        enable_research=run.enable_research,
        manual_research_brief=run.manual_research_brief or "",
        business_context=run.business_context or {},
        category_tags=run.category_tags or [],
        budget_used=run.budget_used,
        variant_count=run.variant_count,
        created_at=run.created_at,
        updated_at=run.updated_at,
        stage_tasks=task_views,
        trace_events=trace_views,
        variant_summary=run_variants(db, run.id).get("summary", {}),
        latest_scorecard=scorecard,
        latest_forecast=forecast,
    )


def _serialize_trace_event(event) -> dict:
    return {
        "id": event.id,
        "run_id": event.run_id,
        "stage_task_id": event.stage_task_id,
        "stage_name": event.stage_name,
        "agent_name": event.agent_name,
        "event_type": event.event_type,
        "visibility": event.visibility,
        "message": event.message,
        "provider_name": event.provider_name,
        "model_name": event.model_name,
        "payload": event.payload or {},
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def _sse_event(event_name: str, payload: dict, event_id: str | None = None) -> str:
    lines = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event_name}")
    lines.append(f"data: {json.dumps(payload, default=str)}")
    return "\n".join(lines) + "\n\n"


def _pipeline_mode_views() -> list[PipelineModeView]:
    labels = {
        PipelineMode.COPY_IMAGE_ONLY.value: "Copy + Image",
        PipelineMode.VIDEO_ONLY.value: "Video",
        PipelineMode.FULL_MULTIMODAL.value: "Full Multimodal",
    }
    views: list[PipelineModeView] = []
    for mode, stages in PIPELINE_STAGE_PLANS.items():
        ordered_agents: list[str] = []
        for stage in stages:
            agent = stage_agent(stage)
            if agent not in ordered_agents:
                ordered_agents.append(agent)
        views.append(
            PipelineModeView(
                mode=mode,
                display_name=labels.get(mode, mode),
                stages=stages,
                agents=ordered_agents,
                agent_count=len(ordered_agents),
            )
        )
    return views


def _serialize_agent_config(row) -> AgentApiConfigView:
    image_cfg = ((row.extra or {}).get("image_config") or {}) if isinstance(row.extra, dict) else {}
    image_key_env = image_cfg.get("api_key_env")
    video_cfg = ((row.extra or {}).get("video_config") or {}) if isinstance(row.extra, dict) else {}
    video_key_env = video_cfg.get("api_key_env")
    # Search tool configs for shop_analyst
    extra_dict = row.extra if isinstance(row.extra, dict) else {}
    tavily_cfg = extra_dict.get("tavily_config") or {}
    firecrawl_cfg = extra_dict.get("firecrawl_config") or {}
    tavily_key_env = tavily_cfg.get("api_key_env")
    firecrawl_key_env = firecrawl_cfg.get("api_key_env")
    thinking_mode = row.thinking_mode or "auto"
    thinking_applied = bool(row.provider_name == "kimi" and row.model_name.startswith("kimi-k") and thinking_mode != "disabled")
    return AgentApiConfigView(
        agent_name=row.agent_name,
        provider_name=row.provider_name,
        model_name=row.model_name,
        api_base_url=row.api_base_url,
        api_key_env=row.api_key_env,
        api_key_available=api_key_available(row.api_key_env),
        image_provider_name=image_cfg.get("provider_name"),
        image_model_name=image_cfg.get("model_name"),
        image_api_base_url=image_cfg.get("api_base_url"),
        image_api_key_env=image_key_env,
        image_api_key_available=api_key_available(image_key_env),
        video_provider_name=video_cfg.get("provider_name"),
        video_model_name=video_cfg.get("model_name"),
        video_api_base_url=video_cfg.get("api_base_url"),
        video_api_key_env=video_key_env,
        video_api_key_available=api_key_available(video_key_env),
        tavily_api_key_env=tavily_key_env,
        tavily_api_key_available=api_key_available(tavily_key_env),
        firecrawl_api_key_env=firecrawl_key_env,
        firecrawl_api_key_available=api_key_available(firecrawl_key_env),
        thinking_mode=row.thinking_mode or "auto",
        thinking_budget_tokens=row.thinking_budget_tokens,
        max_output_tokens=row.max_output_tokens,
        request_timeout_seconds=row.request_timeout_seconds,
        streaming_enabled=bool(row.streaming_enabled),
        thinking_applied=thinking_applied,
        extra=row.extra or {},
        is_default=row.agent_name == "default",
        updated_at=row.updated_at,
    )


# ── Queue monitoring ──────────────────────────────────────


@router.get("/queue/status", response_model=QueueStatusResponse)
def get_queue_status() -> QueueStatusResponse:
    return QueueStatusResponse(**worker.get_queue_status())


@router.get("/queue/running", response_model=list[QueueRunningTask])
def get_queue_running() -> list[QueueRunningTask]:
    return [QueueRunningTask(**item) for item in worker.get_running_tasks()]


@router.get("/queue/health", response_model=QueueHealthResponse)
def get_queue_health() -> QueueHealthResponse:
    return QueueHealthResponse(**worker.get_health())


def _dashboard_shared_js() -> str:
    """Shared JavaScript for dashboard pages: run list, run detail, polling, data sources."""
    return """
        <script>
          let currentRunId = null;
          let pipelineModes = [];
          let dataSources = [];
          let dataSourceSelectInFlight = false;
          let variantBoardFilters = { quality: "", assetType: "", reviewStatus: "", minScore: "", q: "" };
          let runEventSource = null;
          let currentTraceEvents = [];
          let runDetailTimer = null;
          let runDetailLastUpdated = null;
          let runListInterval = null;
          const variantBoardCollapsedStorageKey = "variant_board_collapsed";
          let variantBoardCollapsed = false;
          let expandedVariantId = null;

          function esc(v){ return String(v ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;");}
          function fmtTime(iso){
            if (!iso) return "-";
            const d = new Date(iso);
            if (isNaN(d.getTime())) return iso;
            const MM = String(d.getMonth()+1).padStart(2,'0');
            const DD = String(d.getDate()).padStart(2,'0');
            const hh = String(d.getHours()).padStart(2,'0');
            const mm = String(d.getMinutes()).padStart(2,'0');
            return MM + "-" + DD + " " + hh + ":" + mm;
          }
          function toList(raw){ return String(raw || "").split(",").map(s => s.trim()).filter(Boolean); }
          function parseJsonObject(raw){
            if (!raw || !raw.trim()) return {};
            try { return JSON.parse(raw); } catch (_e) { throw new Error("Advanced Business Context JSON is invalid."); }
          }
          function mediaUrl(path){ return `/media?path=${encodeURIComponent(path || "")}`; }
          function mediaViewUrl(path){ return `/media/view?path=${encodeURIComponent(path || "")}`; }
          function loadVariantBoardCollapsedState() {
            try {
              variantBoardCollapsed = localStorage.getItem(variantBoardCollapsedStorageKey) === "true";
            } catch (_err) {
              variantBoardCollapsed = false;
            }
          }
          function persistVariantBoardCollapsedState() {
            try {
              localStorage.setItem(variantBoardCollapsedStorageKey, variantBoardCollapsed ? "true" : "false");
            } catch (_err) {}
          }

          async function api(path, options = {}) {
            const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
            if (!res.ok) { throw new Error(await res.text()); }
            return res.headers.get("content-type")?.includes("application/json") ? res.json() : res.text();
          }

          async function loadDataSources() {
            const data = await api("/dashboard/data-sources");
            dataSources = data.items || [];
            const sel = document.getElementById("data-source-select");
            sel.innerHTML = "";
            dataSources.forEach((item) => {
              const opt = document.createElement("option");
              opt.value = item.url;
              opt.textContent = item.name;
              if (item.is_active) opt.selected = true;
              sel.appendChild(opt);
            });
            const active = dataSources.find((x) => x.is_active);
            document.getElementById("data-source-path").textContent = active ? active.path : data.active_url;
          }

          async function switchDataSource() {
            if (dataSourceSelectInFlight) return;
            const url = document.getElementById("data-source-select").value;
            if (!url) return;
            dataSourceSelectInFlight = true;
            try {
              await api("/dashboard/data-sources/select", { method: "POST", body: JSON.stringify({ url }) });
              await loadDataSources();
              await refreshRuns();
              if (currentRunId) {
                try { await selectRun(currentRunId); } catch (_err) { document.getElementById("run-detail").innerHTML = "Select a run."; }
              }
            } finally {
              dataSourceSelectInFlight = false;
            }
          }

          function statusPillClass(status) {
            const s = String(status || "").toLowerCase();
            if (s === "running") return "status-pill running";
            if (s === "waiting_review") return "status-pill waiting_review";
            if (s === "completed") return "status-pill completed";
            if (s === "failed") return "status-pill failed";
            if (s === "rejected") return "status-pill rejected";
            return "status-pill draft";
          }
          function statusLabel(status) {
            const s = String(status || "").toLowerCase();
            if (s === "waiting_review") return "REVIEW";
            return String(status || "draft").toUpperCase();
          }
          function modeLabel(mode) {
            const m = String(mode || "");
            if (m === "full_multimodal") return "Full";
            if (m === "video_only") return "Video";
            if (m === "copy_image_only") return "Image";
            return m;
          }

          async function refreshRuns() {
            const rows = await api("/runs");
            const body = document.getElementById("runs-body");
            body.innerHTML = "";
            if (!rows.length) {
              const tr = document.createElement("tr");
              tr.innerHTML = `<td colspan="4" class="muted">No runs available in current data source.</td>`;
              body.appendChild(tr);
              return;
            }
            rows.forEach((r) => {
              const tr = document.createElement("tr");
              if (r.id === currentRunId) tr.classList.add("selected");
              tr.innerHTML = `<td><a href="#" onclick="selectRun('${r.id}');return false;">${r.id.slice(0,8)}</a></td><td><span class="${statusPillClass(r.status)}">${statusLabel(r.status)}</span></td><td>${modeLabel(r.pipeline_mode)}</td><td>${fmtTime(r.updated_at)}</td>`;
              body.appendChild(tr);
            });
          }

          function renderDeliverables(deliverables) {
            const winner = deliverables?.winner_variant_id || "-";
            const copy = deliverables?.deliverables?.copy_variant || null;
            const images = deliverables?.deliverables?.image_assets || [];
            const video = deliverables?.deliverables?.video_asset || null;
            const image = images.length ? images[0] : null;
            const scoreAction = deliverables?.score?.forecast?.recommended_action || deliverables?.score?.recommended_action || "-";
            return `
              <h3>Deliverables Overview</h3>
              <div class="muted">winner: ${esc(winner)} | recommendation: ${esc(scoreAction)}</div>
              <div class="deliverables">
                <article class="deliverable-card">
                  <div class="stage-title">Copy</div>
                  ${copy ? `
                    <div><b>${esc(copy.headline || "-")}</b></div>
                    <div>${esc(copy.primary_text || "-")}</div>
                    <div class="muted">CTA: ${esc(copy.call_to_action || "-")}</div>
                  ` : '<div class="muted">No copy winner yet.</div>'}
                </article>
                <article class="deliverable-card">
                  <div class="stage-title">Image</div>
                  ${image ? `
                    <a href="${mediaViewUrl(image.uri)}" target="_blank">
                      <img class="media-preview image" src="${mediaUrl(image.uri)}" alt="generated image" />
                    </a>
                    <div class="muted">${esc(image.aspect_ratio || "1:1")} | ${esc(image.uri)}</div>
                  ` : '<div class="muted">No image winner yet.</div>'}
                </article>
                <article class="deliverable-card">
                  <div class="stage-title">Video</div>
                  ${video ? `
                    <a href="${mediaViewUrl(video.video_uri)}" target="_blank" class="muted">Open video</a>
                    <video controls playsinline class="media-preview video" src="${mediaUrl(video.video_uri)}"></video>
                    <div class="muted">${esc(video.video_uri)}</div>
                  ` : '<div class="muted">No video winner yet.</div>'}
                </article>
              </div>
            `;
          }

          function latestScore(item, scoreType){
            const rows = (item?.scores || []).filter((row) => row.score_type === scoreType);
            return rows.length ? rows[rows.length - 1] : null;
          }

          function assetsByType(item, type){
            return (item?.assets || []).filter((asset) => asset.asset_type === type);
          }

          function qualitySummary(item){
            return item?.quality_summary || {};
          }

          function qualityFlags(item){
            return qualitySummary(item).quality_flags || [];
          }

          function qualityChipClass(flag){
            if (["ready_to_review", "winner", "shortlisted"].includes(flag)) return "good";
            if (["processing_assets", "missing_assets", "compliance_attention", "low_score", "pending_review", "visual_qa_attention", "visual_qa_needs_frame_review", "visual_qa_remote_unchecked", "visual_qa_aspect_mismatch", "visual_qa_low_information", "visual_qa_video_header_unverified"].includes(flag)) return "warn";
            if (["failed_assets", "media_issue", "operator_quality_issue", "needs_regeneration", "rejected", "visual_qa_failed", "visual_qa_placeholder", "visual_qa_empty_video", "visual_qa_decode_error", "visual_qa_empty_file", "visual_qa_missing_file"].includes(flag)) return "bad";
            return "";
          }

          function variantMatchesOperationalFilters(item){
            const quality = variantBoardFilters.quality;
            const assetType = variantBoardFilters.assetType;
            const reviewStatus = variantBoardFilters.reviewStatus;
            const minScoreRaw = variantBoardFilters.minScore;
            const q = String(variantBoardFilters.q || "").trim().toLowerCase();
            const summary = qualitySummary(item);
            const flags = new Set(summary.quality_flags || []);
            if (quality && summary.quality_status !== quality && !flags.has(quality)) return false;
            if (assetType && !(summary.asset_counts || {})[assetType]) return false;
            if (reviewStatus && (item.review_status || "") !== reviewStatus) return false;
            if (minScoreRaw) {
              const minScore = Number(minScoreRaw);
              const score = Number(summary.score ?? item.current_score);
              if (!Number.isFinite(minScore) || !Number.isFinite(score) || score < minScore) return false;
            }
            if (q) {
              const haystack = [item.variant_id, item.angle, item.hook, item.message, item.strategy_brief?.rationale].join(" ").toLowerCase();
              if (!haystack.includes(q)) return false;
            }
            return true;
          }

          async function updateVariantFilter(field, value){
            variantBoardFilters = { ...variantBoardFilters, [field]: value };
            if (currentRunId) await selectRun(currentRunId);
          }

          function resetVariantFilters(){
            variantBoardFilters = { quality: "", assetType: "", reviewStatus: "", minScore: "", q: "" };
            if (currentRunId) selectRun(currentRunId);
          }
          function variantBoardToggleLabel() {
            return variantBoardCollapsed ? "Expand Variant Board" : "Collapse Variant Board";
          }
          function toggleVariantBoard(){
            variantBoardCollapsed = !variantBoardCollapsed;
            persistVariantBoardCollapsedState();
            const body = document.getElementById("variant-board-body");
            if (body) body.classList.toggle("is-collapsed", variantBoardCollapsed);
            const btn = document.getElementById("variant-board-toggle");
            if (btn) btn.textContent = variantBoardToggleLabel();
          }

          async function variantAction(runId, variantId, endpoint, body){
            await api(endpoint, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(body)
            });
            await selectRun(runId);
          }

          async function refreshAsyncAssets(runId){
            await api(`/runs/${runId}/assets/refresh`, { method: "POST" });
            await selectRun(runId);
          }

          async function requestVariantRegeneration(runId, variantId){
            const targetStage = window.prompt("Target stage: copy_image_generation, video_scripting, storyboard_image_generation, or video_generation. Leave blank for default.", "");
            if (targetStage === null) return;
            const reason = window.prompt("Regeneration reason", "dashboard regeneration request");
            if (reason === null) return;
            await variantAction(runId, variantId, `/runs/${runId}/variants/${variantId}/regenerate`, {
              reason: reason || "dashboard regeneration request",
              target_stage: targetStage.trim() || null
            });
          }

          function scoreColorClass(score) {
            if (score == null) return "";
            if (score >= 80) return "high";
            if (score >= 60) return "mid";
            return "low";
          }

          function renderScoreBreakdown(item) {
            const evaluation = latestScore(item, "evaluation");
            const subs = evaluation?.sub_scores || {};
            const bars = [
              { key: "hook_strength", label: "Hook" },
              { key: "clarity", label: "Clarity" },
              { key: "generation_fit", label: "Gen Fit" },
              { key: "visual_qa", label: "Vis QA" },
              { key: "compliance", label: "Compliance" },
              { key: "ai_naturalness", label: "AI Natural" },
            ];
            return bars.map((b) => {
              const val = subs[b.key] != null ? Number(subs[b.key]) : 0;
              return `
                <div class="score-item">
                  <span>${b.label}</span>
                  <div class="bar"><div class="bar-fill" style="width:${Math.min(100, val)}%"></div></div>
                  <span style="min-width:36px;text-align:right;font-weight:700;">${Math.round(val)}</span>
                </div>
              `;
            }).join("");
          }

          function toggleVariantDetail(runId, variantId) {
            const panel = document.getElementById("variant-detail-panel");
            const cards = document.querySelectorAll(".variant-score-card");
            if (expandedVariantId === variantId) {
              expandedVariantId = null;
              if (panel) panel.classList.remove("open");
              cards.forEach((c) => c.classList.remove("selected"));
              return;
            }
            expandedVariantId = variantId;
            cards.forEach((c) => {
              c.classList.toggle("selected", c.dataset.variantId === variantId);
            });
            if (panel) {
              panel.innerHTML = renderVariantDetail(runId, variantId);
              panel.classList.add("open");
              panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
            }
          }

          function renderVariantDetail(runId, variantId) {
            const allItems = window.__lastVariants?.items || [];
            const item = allItems.find((v) => v.variant_id === variantId);
            if (!item) return '<div class="muted">Variant not found.</div>';
            const copy = assetsByType(item, "copy")[0]?.payload || null;
            const images = assetsByType(item, "image");
            const image = images[0] || null;
            const script = assetsByType(item, "video_script")[0]?.payload || null;
            const videoAsset = assetsByType(item, "video")[0] || null;
            const video = videoAsset?.payload || null;
            const evaluation = latestScore(item, "evaluation");
            const score = evaluation?.total_score;
            const qSummary = qualitySummary(item);
            const flags = qualityFlags(item);
            const qualityChips = flags.map((flag) => `<span class="quality-chip ${qualityChipClass(flag)}">${esc(flag)}</span>`).join("");
            return `
              <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
                <div>
                  <b style="font-size:18px;">${esc(item.variant_id)}</b>
                  <span class="muted"> · ${esc(item.angle || "-")}</span>
                  ${item.is_winner ? '<span class="quality-chip good">Winner</span>' : ''}
                  ${item.shortlisted ? '<span class="quality-chip good">Shortlisted</span>' : ''}
                </div>
                <button onclick="expandedVariantId=null;document.getElementById('variant-detail-panel').classList.remove('open');document.querySelectorAll('.variant-score-card').forEach(c=>c.classList.remove('selected'));" style="font-size:12px;">Close</button>
              </div>
              <div class="variant-detail-grid" style="margin-top:14px;">
                <div>
                  ${image ? `<a href="${mediaViewUrl(image.uri)}" target="_blank"><img class="detail-image" src="${mediaUrl(image.uri)}" alt="variant image" /></a>` : '<div class="muted">No image asset.</div>'}
                  ${video?.video_uri ? `
                    <div style="margin-top:10px;">
                      <video controls playsinline class="media-preview video" src="${mediaUrl(video.video_uri)}" style="max-height:400px;"></video>
                    </div>
                  ` : ''}
                </div>
                <div>
                  <div style="display:flex;align-items:baseline;gap:10px;margin-bottom:10px;">
                    <span class="score-number ${scoreColorClass(score)}" style="font-size:42px;">${score != null ? Math.round(score) : "-"}</span>
                    <span class="muted">/ 100</span>
                    <span class="quality-chip ${qualityChipClass(qSummary.quality_status)}">${esc(qSummary.quality_status || "-")}</span>
                  </div>
                  <div class="variant-score-breakdown">${renderScoreBreakdown(item)}</div>
                  <div class="quality-row" style="margin-top:10px;">${qualityChips}</div>
                </div>
              </div>
              <div style="margin-top:14px;">
                <div><b>Hook</b>: ${esc(item.hook || "-")}</div>
                <div style="margin-top:6px;"><b>Message</b>: ${esc(item.message || "-")}</div>
                <div style="margin-top:6px;"><b>Headline</b>: ${esc(copy?.headline || "-")}</div>
                <div class="muted">${esc(copy?.primary_text || "-")}</div>
                ${script ? `<div style="margin-top:8px;"><b>Script</b>: ${esc(script.hook || "-")}<div class="muted">${esc(script.script || "-")}</div></div>` : ''}
                <div class="muted" style="margin-top:6px;">CTA: ${esc(copy?.call_to_action || "-")} | action: ${esc(evaluation?.recommended_action || "-")}</div>
              </div>
              <div class="variant-detail-actions">
                <button onclick="variantAction('${runId}', '${variantId}', '/runs/${runId}/variants/${variantId}/review', {action:'approve_variant', comment:'approved from dashboard'})">Approve</button>
                <button onclick="variantAction('${runId}', '${variantId}', '/runs/${runId}/variants/${variantId}/review', {action:'reject_variant', comment:'rejected from dashboard'})">Reject</button>
                <button onclick="variantAction('${runId}', '${variantId}', '/runs/${runId}/variants/${variantId}/select', {shortlist:true, comment:'shortlisted from dashboard'})">Shortlist</button>
                <button class="primary" onclick="variantAction('${runId}', '${variantId}', '/runs/${runId}/variants/${variantId}/select', {winner:true, comment:'winner chosen from dashboard'})">Set Winner</button>
                <button onclick="requestVariantRegeneration('${runId}', '${variantId}')">Regenerate</button>
              </div>
            `;
          }

          function renderVariantBoard(runId, variants){
            window.__lastVariants = variants;
            const allItems = variants?.items || [];
            const items = allItems.filter(variantMatchesOperationalFilters);
            const summary = variants?.summary || {};
            const qualityCounts = summary.quality_flag_counts || {};
            const header = `<div class="muted">showing: ${esc(items.length)} / ${esc(summary.total || allItems.length || 0)} | shortlisted: ${esc(summary.shortlisted_count || 0)} | winners: ${esc(summary.winner_count || 0)} | regen requests: ${esc(summary.regeneration_requested_count || 0)} | asset issues: ${esc((qualityCounts.failed_assets || 0) + (qualityCounts.media_issue || 0))} | processing: ${esc(qualityCounts.processing_assets || 0)}</div>`;
            const filters = `
              <div class="variant-filter-bar">
                <div>
                  <label>Quality</label>
                  <select onchange="updateVariantFilter('quality', this.value)">
                    <option value="" ${variantBoardFilters.quality === "" ? "selected" : ""}>All</option>
                    <option value="ready_to_review" ${variantBoardFilters.quality === "ready_to_review" ? "selected" : ""}>Ready</option>
                    <option value="winner" ${variantBoardFilters.quality === "winner" ? "selected" : ""}>Winner</option>
                    <option value="shortlisted" ${variantBoardFilters.quality === "shortlisted" ? "selected" : ""}>Shortlisted</option>
                    <option value="pending_review" ${variantBoardFilters.quality === "pending_review" ? "selected" : ""}>Pending</option>
                    <option value="processing_assets" ${variantBoardFilters.quality === "processing_assets" ? "selected" : ""}>Processing</option>
                    <option value="failed_assets" ${variantBoardFilters.quality === "failed_assets" ? "selected" : ""}>Failed</option>
                    <option value="visual_qa_attention" ${variantBoardFilters.quality === "visual_qa_attention" ? "selected" : ""}>QA Attn</option>
                    <option value="visual_qa_failed" ${variantBoardFilters.quality === "visual_qa_failed" ? "selected" : ""}>QA Fail</option>
                    <option value="needs_regeneration" ${variantBoardFilters.quality === "needs_regeneration" ? "selected" : ""}>Regen</option>
                    <option value="rejected" ${variantBoardFilters.quality === "rejected" ? "selected" : ""}>Rejected</option>
                  </select>
                </div>
                <div>
                  <label>Asset</label>
                  <select onchange="updateVariantFilter('assetType', this.value)">
                    <option value="" ${variantBoardFilters.assetType === "" ? "selected" : ""}>Any</option>
                    <option value="copy" ${variantBoardFilters.assetType === "copy" ? "selected" : ""}>Copy</option>
                    <option value="image" ${variantBoardFilters.assetType === "image" ? "selected" : ""}>Image</option>
                    <option value="video_script" ${variantBoardFilters.assetType === "video_script" ? "selected" : ""}>Script</option>
                    <option value="video" ${variantBoardFilters.assetType === "video" ? "selected" : ""}>Video</option>
                  </select>
                </div>
                <div>
                  <label>Review</label>
                  <select onchange="updateVariantFilter('reviewStatus', this.value)">
                    <option value="" ${variantBoardFilters.reviewStatus === "" ? "selected" : ""}>Any</option>
                    <option value="approved" ${variantBoardFilters.reviewStatus === "approved" ? "selected" : ""}>Approved</option>
                    <option value="shortlisted" ${variantBoardFilters.reviewStatus === "shortlisted" ? "selected" : ""}>Shortlisted</option>
                    <option value="winner" ${variantBoardFilters.reviewStatus === "winner" ? "selected" : ""}>Winner</option>
                    <option value="rejected" ${variantBoardFilters.reviewStatus === "rejected" ? "selected" : ""}>Rejected</option>
                  </select>
                </div>
                <div>
                  <label>Min Score</label>
                  <input type="number" min="0" max="100" value="${esc(variantBoardFilters.minScore)}" onchange="updateVariantFilter('minScore', this.value)" placeholder="e.g. 80" style="width:72px;" />
                </div>
                <div>
                  <label>Search</label>
                  <div style="display:flex;gap:6px;align-items:center;">
                    <input value="${esc(variantBoardFilters.q)}" onchange="updateVariantFilter('q', this.value)" placeholder="angle, hook" style="width:96px;" />
                    <button onclick="resetVariantFilters()" style="font-size:11px;padding:5px 8px;white-space:nowrap;" title="Clear all filters">&#8634; Reset</button>
                  </div>
                </div>
              </div>
            `;
            if (!allItems.length) {
              return `
                <div class="variant-board-header">
                  <h3>Variant Board</h3>
                  <button id="variant-board-toggle" class="variant-toggle-btn" onclick="toggleVariantBoard()">${variantBoardToggleLabel()}</button>
                </div>
                <div id="variant-board-body" class="variant-board-body ${variantBoardCollapsed ? "is-collapsed" : ""}">
                  ${header}
                  <div class="run-detail-empty">No variants materialized yet.</div>
                </div>
              `;
            }
            if (!items.length) {
              return `
                <div class="variant-board-header">
                  <h3>Variant Board</h3>
                  <button id="variant-board-toggle" class="variant-toggle-btn" onclick="toggleVariantBoard()">${variantBoardToggleLabel()}</button>
                </div>
                <div id="variant-board-body" class="variant-board-body ${variantBoardCollapsed ? "is-collapsed" : ""}">
                  ${header}
                  ${filters}
                  <div class="run-detail-empty">No variants match the active filters.</div>
                </div>
              `;
            }
            const scoreCards = items.map((item, idx) => {
              const images = assetsByType(item, "image");
              const image = images[0] || null;
              const evaluation = latestScore(item, "evaluation");
              const score = evaluation?.total_score;
              const qSummary = qualitySummary(item);
              return `
                <article class="variant-score-card" data-variant-id="${esc(item.variant_id)}" onclick="toggleVariantDetail('${runId}', '${item.variant_id}')">
                  <div class="rank-badge">${idx + 1}</div>
                  <div class="stage-title">${esc(item.variant_id)}</div>
                  <div class="muted" style="font-size:11px;">${esc(item.angle || "-")}</div>
                  <div class="score-number ${scoreColorClass(score)}">${score != null ? Math.round(score) : "-"}</div>
                  ${image ? `<img class="thumb" src="${mediaUrl(image.uri)}" alt="variant thumbnail" />` : '<div class="thumb muted" style="display:flex;align-items:center;justify-content:center;font-size:11px;">No image</div>'}
                  <div class="quality-row" style="justify-content:center;">
                    ${item.is_winner ? '<span class="quality-chip good">Winner</span>' : ''}
                    ${item.shortlisted && !item.is_winner ? '<span class="quality-chip good">Shortlisted</span>' : ''}
                    <span class="quality-chip ${qualityChipClass(qSummary.quality_status)}">${esc(qSummary.quality_status || "-")}</span>
                  </div>
                  <div class="quick-actions">
                    <button class="primary" onclick="event.stopPropagation();variantAction('${runId}', '${item.variant_id}', '/runs/${runId}/variants/${item.variant_id}/select', {winner:true, comment:'winner chosen from dashboard'})">Set Winner</button>
                    <button onclick="event.stopPropagation();variantAction('${runId}', '${item.variant_id}', '/runs/${runId}/variants/${item.variant_id}/select', {shortlist:true, comment:'shortlisted from dashboard'})">Shortlist</button>
                  </div>
                </article>
              `;
            }).join("");
            const detailPanel = expandedVariantId
              ? `<div id="variant-detail-panel" class="variant-detail-panel open">${renderVariantDetail(runId, expandedVariantId)}</div>`
              : `<div id="variant-detail-panel" class="variant-detail-panel"></div>`;
            return `
              <div class="variant-board-header">
                <h3>Variant Board</h3>
                <button id="variant-board-toggle" class="variant-toggle-btn" onclick="toggleVariantBoard()">${variantBoardToggleLabel()}</button>
              </div>
              <div id="variant-board-body" class="variant-board-body ${variantBoardCollapsed ? "is-collapsed" : ""}">
                ${header}
                ${filters}
                <div class="variant-scoreboard">${scoreCards}</div>
                ${detailPanel}
              </div>
            `;
          }

          function renderTimeline(run) {
            const stages = run.stage_tasks || [];
            if (!stages.length) return '<div class="run-detail-empty">No stage logs yet.</div>';
            return `
              <div id="timeline-board" class="agent-trace">
                ${stages.map((task, index) => {
                  const agent = task.metadata_json?.agent_name || "-";
                  const isAutoApproved = task.status === "approved" && String(task.review_notes || "").includes("auto_approved");
                  const statusLabel = isAutoApproved ? "AUTO-APPROVED" : esc(task.status);
                  return `
                <article class="trace-event">
                  <div class="trace-head">
                    <div class="trace-head-main">
                      <span class="trace-index">${stages.length - index}</span>
                      <span class="pill">${esc(task.stage_name)}</span>
                    </div>
                    <div class="muted">${esc(task.started_at || "-")}</div>
                  </div>
                  <div style="display:flex;gap:4px;flex-wrap:wrap;margin:4px 0;">
                    <span class="pill">${statusLabel}</span>
                    <span class="pill">attempt ${esc(task.attempt)}</span>
                    <span class="pill">${esc(agent)}</span>
                    ${isAutoApproved ? '<span class="quality-chip good">auto</span>' : ""}
                  </div>
                  <div class="trace-message">${esc(task.summary || "No summary")}</div>
                  <div class="muted" style="margin-top:4px;">review: ${isAutoApproved ? '<span class="quality-chip good">AUTO-APPROVED</span>' : esc(task.review_notes || "-")}</div>
                  <details class="trace-payload">
                    <summary>Stage payload</summary>
                    <pre>${esc(JSON.stringify(task.output_payload || {}, null, 2))}</pre>
                  </details>
                </article>
                  `;
                }).join("")}
              </div>
            `;
          }

          function renderAgentTrace(run) {
            const events = [...(run.trace_events || currentTraceEvents || [])].sort((a, b) => {
              const ta = Date.parse(a.created_at || "") || 0;
              const tb = Date.parse(b.created_at || "") || 0;
              if (ta !== tb) return tb - ta;
              return String(b.id || "").localeCompare(String(a.id || ""));
            });
            if (!events.length) return '<div class="run-detail-empty">No agent trace events yet.</div>';
            return `
              <div id="agent-trace-board" class="agent-trace">
                ${events.map((event, index) => `
                  <article class="trace-event">
                    <div class="trace-head">
                      <div class="trace-head-main">
                        <span class="trace-index">${events.length - index}</span>
                        <span class="pill">${esc(event.stage_name)}</span>
                        <span class="pill">${esc(event.agent_name)}</span>
                        <span class="pill">${esc(event.event_type)}</span>
                      </div>
                      <div class="muted">${esc(event.created_at)}</div>
                    </div>
                    <div class="trace-message">${esc(event.message || "-")}</div>
                    <div class="muted" style="margin-top:4px;">provider/model: ${esc(event.provider_name || "-")} / ${esc(event.model_name || "-")}</div>
                    <details class="trace-payload">
                      <summary>Trace payload</summary>
                      <pre>${esc(JSON.stringify(event.payload || {}, null, 2))}</pre>
                    </details>
                  </article>
                `).join("")}
              </div>
            `;
          }
          function isNearTraceLeftEdge(container){
            if (!container) return true;
            return container.scrollLeft <= 48;
          }
          function scrollTraceToLeft(behavior = "smooth"){
            const container = document.getElementById("agent-trace-board");
            if (!container) return;
            container.scrollTo({ left: 0, behavior });
          }
          function bindTracePayloadToggles(){
            ["agent-trace-board", "timeline-board"].forEach((id) => {
              const container = document.getElementById(id);
              if (!container) return;
              container.querySelectorAll(".trace-payload").forEach((details) => {
                if (details.dataset.bound === "1") return;
                details.dataset.bound = "1";
                details.addEventListener("toggle", () => {
                  const card = details.closest(".trace-event");
                  if (!card) return;
                  card.classList.toggle("trace-event-expanded", details.open);
                if (details.open) {
                  requestAnimationFrame(() => {
                    card.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "nearest" });
                  });
                }
              });
            });
            });
          }

          function connectRunEvents(runId){
            if (runEventSource) {
              runEventSource.close();
              runEventSource = null;
            }
            if (!window.EventSource) return;
            runEventSource = new EventSource(`/runs/${runId}/events`);
            runEventSource.addEventListener("agent_trace", (event) => {
              try {
                const item = JSON.parse(event.data);
                if (currentRunId !== runId) return;
                if (!currentTraceEvents.some((existing) => existing.id === item.id)) {
                  const containerBefore = document.getElementById("agent-trace-board");
                  const shouldStickToLeft = isNearTraceLeftEdge(containerBefore);
                  currentTraceEvents.unshift(item);
                  const container = document.getElementById("agent-trace-container");
                  if (container) {
                    container.innerHTML = renderAgentTrace({ trace_events: currentTraceEvents });
                    bindTracePayloadToggles();
                    if (shouldStickToLeft) {
                      requestAnimationFrame(() => scrollTraceToLeft("smooth"));
                    }
                  }
                }
              } catch (_err) {}
            });
          }

          function startRunDetailPolling(runId) {
            stopRunDetailPolling();
            runDetailTimer = setInterval(async () => {
              if (!document.hidden) {
                try {
                  const run = await api(`/runs/${runId}`);
                  const newUpdated = run.updated_at;
                  if (runDetailLastUpdated === newUpdated) return;
                  runDetailLastUpdated = newUpdated;
                  await silentRefreshRunDetail(run);
                } catch (_err) {}
              }
            }, 3000);
          }

          function stopRunDetailPolling() {
            if (runDetailTimer) {
              clearInterval(runDetailTimer);
              runDetailTimer = null;
            }
            runDetailLastUpdated = null;
          }

          async function silentRefreshRunDetail(run) {
            const wasCollapsed = variantBoardCollapsed;
            const wasExpandedVariantId = expandedVariantId;
            const traceBoard = document.getElementById("agent-trace-board");
            const traceScrollLeft = traceBoard ? traceBoard.scrollLeft : 0;

            const [deliverables, variants] = await Promise.all([
              api(`/runs/${run.id}/deliverables`).catch(() => ({ run_id: run.id, deliverables: {}, score: {} })),
              api(`/runs/${run.id}/variants`).catch(() => ({ run_id: run.id, items: [], summary: {}, variants: [], ranked: [] }))
            ]);

            // Merge: keep SSE-streamed events not yet on server, add server events on top
            const serverEventIds = new Set((run.trace_events || []).map(e => e.id));
            const sseOnly = currentTraceEvents.filter(e => !serverEventIds.has(e.id));
            currentTraceEvents = [...sseOnly, ...(run.trace_events || [])];
            run.trace_events = currentTraceEvents;

            expandedVariantId = wasExpandedVariantId;
            document.getElementById("run-detail").innerHTML = renderRunDetail(run, deliverables, variants);

            if (wasCollapsed) {
              const body = document.getElementById("variant-board-body");
              if (body) body.classList.add("is-collapsed");
              const btn = document.getElementById("variant-board-toggle");
              if (btn) btn.textContent = variantBoardToggleLabel();
            }
            if (wasExpandedVariantId) {
              const panel = document.getElementById("variant-detail-panel");
              if (panel && !panel.classList.contains("open")) {
                panel.innerHTML = renderVariantDetail(run.id, wasExpandedVariantId);
                panel.classList.add("open");
              }
            }
            const newTraceBoard = document.getElementById("agent-trace-board");
            if (newTraceBoard && traceScrollLeft > 0) {
              newTraceBoard.scrollLeft = traceScrollLeft;
            }
            bindTracePayloadToggles();
          }

          function renderRunDetail(run, deliverables, variants){
            const score = run.latest_scorecard ? `<pre>${esc(JSON.stringify(run.latest_scorecard, null, 2))}</pre>` : `<span class="muted">No score yet.</span>`;
            return `
              <div style="margin-bottom:12px;">
                <div><b>Run:</b> ${esc(run.id)}</div>
                <div><span class="${statusPillClass(run.status)}">${statusLabel(run.status)}</span> <span class="pill">stage: ${esc(run.current_stage || "-")}</span><span class="pill">mode: ${esc(run.pipeline_mode)}</span><span class="pill">approval: ${esc(run.approval_mode || "manual")}</span></div>
                <div class="muted">provider/model: ${esc(run.model_provider)} / ${esc(run.model_name)} | budget: ${esc(run.budget_used)}</div>
                <div class="muted">product_code: ${esc(run.product_code)} | industry_code: ${esc(run.industry_code)} | creative_preset: ${esc(run.creative_preset)}</div>
                <div class="muted">creative_specs: ${esc(JSON.stringify(run.creative_specs || {}))}</div>
                <div class="muted">variant_summary: ${esc(JSON.stringify(run.variant_summary || {}))}</div>
                <div style="margin-top:8px;"><button onclick="refreshAsyncAssets('${run.id}')">Refresh async assets</button></div>
              </div>
              ${renderDeliverables(deliverables)}
              ${renderVariantBoard(run.id, variants)}
              <h3 style="margin-top:14px;">Agent Trace</h3>
              <div id="agent-trace-container">${renderAgentTrace(run)}</div>
              <h3 style="margin-top:14px;">Stage Timeline</h3>
              ${renderTimeline(run)}
              <h3 style="margin-top:14px;">Latest Scorecard</h3>
              ${score}
            `;
          }

          async function selectRun(runId){
            currentRunId = runId;
            expandedVariantId = null;
            document.getElementById('fab-advance').classList.add('visible');
            document.getElementById('fab-reject').classList.add('visible');
            const [run, deliverables, variants] = await Promise.all([
              api(`/runs/${runId}`),
              api(`/runs/${runId}/deliverables`).catch(() => ({ run_id: runId, deliverables: {}, score: {} })),
              api(`/runs/${runId}/variants`).catch(() => ({ run_id: runId, items: [], summary: {}, variants: [], ranked: [] }))
            ]);
            currentTraceEvents = run.trace_events || [];
            runDetailLastUpdated = run.updated_at;
            document.getElementById("run-detail").innerHTML = renderRunDetail(run, deliverables, variants);
            bindTracePayloadToggles();
            requestAnimationFrame(() => scrollTraceToLeft("auto"));
            connectRunEvents(runId);
            startRunDetailPolling(runId);
          }

          async function loadPipelineModes(){
            pipelineModes = await api("/pipeline-modes");
            const sel = document.getElementById("pipeline_mode");
            sel.innerHTML = "";
            pipelineModes.forEach((m) => {
              const opt = document.createElement("option");
              opt.value = m.mode;
              opt.textContent = `${m.display_name}`;
              if (m.mode === "copy_image_only") opt.selected = true;
              sel.appendChild(opt);
            });
            refreshModeHint();
          }

          function refreshModeHint(){
            const mode = document.getElementById("pipeline_mode").value;
            const chosen = pipelineModes.find((m) => m.mode === mode);
            if (!chosen) return;
            const text = `Stages: ${chosen.stages.join(" -> ")} | Active agents (${chosen.agent_count}): ${chosen.agents.join(", ")}`;
            document.getElementById("mode-summary").textContent = text;
          }

          function refreshResearchHint(){
            const mode = document.getElementById("research_mode").value;
            const hint = document.getElementById("research-hint");
            if (mode === "autonomous_web") {
              hint.textContent = "Autonomous web research will run in planning and may be slower due to online fetches.";
            } else {
              hint.textContent = "Planning will rely on your manual notes and uploaded assets only (recommended for fast debugging).";
            }
          }

          function detectInputKinds(files){
            let hasImageInputs = false;
            let hasVideoInputs = false;
            for (let i = 0; i < files.length; i++) {
              const name = (files[i].name || "").toLowerCase();
              if (name.endsWith(".png") || name.endsWith(".jpg") || name.endsWith(".jpeg") || name.endsWith(".webp")) hasImageInputs = true;
              if (name.endsWith(".mp4") || name.endsWith(".mov") || name.endsWith(".m4v")) hasVideoInputs = true;
            }
            return { hasImageInputs, hasVideoInputs };
          }

          function preflightDetail(preflight){
            const rows = (preflight.checks || []).filter((row) => row.severity !== "ok");
            if (!rows.length) return preflight.summary || "No compatibility risk detected.";
            return rows.map((row) => {
              const scope = [row.stage_name, row.agent_name].filter(Boolean).join(" / ");
              return `[${row.severity.toUpperCase()}] ${scope ? scope + ": " : ""}${row.message}`;
            }).join("\\n");
          }

          async function advanceRun(){
            if(!currentRunId) return;
            await api(`/runs/${currentRunId}/advance`, { method:"POST", body: JSON.stringify({notes:"approved"})});
            await selectRun(currentRunId);
            await refreshRuns();
          }

          async function rejectRun(){
            if(!currentRunId) return;
            await api(`/runs/${currentRunId}/reject`, { method:"POST", body: JSON.stringify({notes:"rejected"})});
            await selectRun(currentRunId);
            await refreshRuns();
          }

          function startRunListPolling() {
            if (runListInterval) return;
            runListInterval = setInterval(async () => {
              if (!document.hidden) await refreshRuns();
            }, 5000);
            updateRefreshIndicator(true);
          }

          function stopRunListPolling() {
            if (runListInterval) {
              clearInterval(runListInterval);
              runListInterval = null;
            }
            updateRefreshIndicator(false);
          }

          function updateRefreshIndicator(active) {
            const indicator = document.getElementById("runs-refresh-indicator");
            if (!indicator) return;
            if (active) {
              indicator.classList.add("active");
              indicator.title = "Auto-refreshing every 5s";
            } else {
              indicator.classList.remove("active");
              indicator.title = "Auto-refresh paused (tab hidden)";
            }
          }

          document.addEventListener("visibilitychange", () => {
            if (document.hidden) {
              updateRefreshIndicator(false);
            } else {
              updateRefreshIndicator(true);
              refreshRuns();
              if (currentRunId) {
                stopRunDetailPolling();
                startRunDetailPolling(currentRunId);
              }
            }
          });

          refreshResearchHint();
          loadVariantBoardCollapsedState();
          loadPipelineModes();
          loadDataSources().then(async () => {
            await refreshRuns();
            const hash = window.location.hash || "";
            if (hash.startsWith("#run=")) {
              const runId = hash.replace("#run=", "");
              if (runId) {
                try { await selectRun(runId); } catch (_err) {}
              }
            }
          });
          startRunListPolling();
        </script>
    """
@router.get("/dashboard/shop-analysis", response_class=HTMLResponse)
def dashboard_shop_analysis() -> str:
    return _shop_analysis_page_html()


def _shop_analysis_page_html() -> str:
    return """
    <html>
      <head>
        <title>Crispy Shop Analysis</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>
          :root {
            --bg: #f4f7f2;
            --bg-alt: #e8f2f8;
            --card: rgba(255, 255, 255, 0.92);
            --text: #183329;
            --muted: #5e6e66;
            --line: #d8e5dc;
            --accent: #1f7a62;
            --radius: 16px;
            --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
          }
          * { box-sizing: border-box; }
          body {
            margin: 0;
            color: var(--text);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
            background:
              radial-gradient(circle at 10% -20%, #d9ede6 0%, transparent 40%),
              radial-gradient(circle at 90% -20%, #d8e9f6 0%, transparent 42%),
              linear-gradient(180deg, var(--bg-alt), var(--bg) 30%);
          }
          .app-shell { width: min(1100px, calc(100% - 24px)); margin: 22px auto 30px auto; }
          .hero { display:flex; justify-content: space-between; align-items: flex-end; gap: 12px; margin-bottom: 14px; }
          h1, h2, h3 { margin: 0; line-height: 1.25; }
          h1 { font-size: 27px; letter-spacing: -0.02em; }
          h2 { font-size: 19px; margin-bottom: 10px; }
          .subtitle { margin-top: 6px; color: var(--muted); font-size: 14px; }
          .muted { color: var(--muted); font-size: 12px; }
          a { color: #135f4c; text-decoration: none; }
          a:hover { text-decoration: underline; }
          .nav-link {
            border: 1px solid var(--line);
            background: #fff;
            padding: 8px 12px;
            border-radius: 999px;
            font-size: 13px;
            font-weight: 600;
          }
          .card {
            border: 1px solid var(--line);
            border-radius: var(--radius);
            padding: 20px;
            background: var(--card);
            box-shadow: 0 8px 24px rgba(30, 62, 50, 0.07);
            margin-bottom: 16px;
          }
          input, textarea, select {
            width: 100%;
            border: 1px solid var(--line);
            border-radius: 10px;
            padding: 10px 12px;
            font-family: inherit;
            font-size: 14px;
            background: #fff;
            color: var(--text);
          }
          input:focus, textarea:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(31, 122, 98, 0.15); }
          label { display: block; font-weight: 600; font-size: 13px; margin-bottom: 3px; }
          button {
            border: 1px solid var(--line);
            border-radius: 10px;
            padding: 10px 18px;
            font-family: inherit;
            font-size: 14px;
            cursor: pointer;
            background: #fff;
            color: var(--text);
            font-weight: 600;
            transition: background 0.15s;
          }
          button:hover { background: #f0f5f2; }
          button.primary { background: var(--accent); color: #fff; border-color: var(--accent); }
          button.primary:hover { background: #145746; }
          button:disabled { opacity: 0.5; cursor: not-allowed; }
          .form-row { display: flex; gap: 12px; align-items: flex-end; flex-wrap: wrap; }
          .form-row > div { flex: 1; min-width: 200px; }
          .result-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
          .result-panel {
            border: 1px solid var(--line);
            border-radius: 12px;
            padding: 16px;
            background: #fafdfb;
            max-height: 600px;
            overflow-y: auto;
          }
          .result-panel pre {
            white-space: pre-wrap;
            word-break: break-word;
            font-family: var(--mono);
            font-size: 12px;
            line-height: 1.5;
          }
          .history-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 14px;
            border-bottom: 1px solid var(--line);
            font-size: 13px;
          }
          .history-item:last-child { border-bottom: none; }
          .status-badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 999px;
            font-size: 11px;
            font-weight: 700;
          }
          .status-badge.completed { background: #eaf7ee; color: #21633d; }
          .status-badge.failed { background: #fdeeee; color: #8a2d2d; }
          .status-badge.running { background: #fff7e6; color: #8a5d1c; }
          .loading { text-align: center; padding: 32px; color: var(--muted); }
          .loading .spinner {
            display: inline-block;
            width: 24px; height: 24px;
            border: 3px solid var(--line);
            border-top-color: var(--accent);
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
          }
          @keyframes spin { to { transform: rotate(360deg); } }
          @media (max-width: 860px) {
            .result-grid { grid-template-columns: 1fr; }
            .form-row > div { min-width: 100%; }
          }
        </style>
      </head>
      <body>
        <main class="app-shell">
          <header class="hero">
            <div>
              <h1>Shop Analysis</h1>
              <div class="subtitle">Research store positioning, SEO, and competitive landscape. Results feed into GM memory for creative strategy.</div>
            </div>
            <a class="nav-link" href="/dashboard">Back to Dashboard</a>
          </header>

          <section class="card">
            <h2>New Analysis</h2>
            <div class="form-row">
              <div>
                <label>Store URL (required)</label>
                <input id="store-url" type="url" placeholder="https://example.com" />
              </div>
              <div>
                <label>Industry Code</label>
                <input id="industry-code" value="general" placeholder="e.g. pet_accessories" />
              </div>
            </div>
            <div style="margin-top:10px;">
              <label>Store Description (optional)</label>
              <textarea id="store-description" rows="2" placeholder="Brief description: what they sell, target market, known positioning..."></textarea>
            </div>
            <div style="margin-top:12px;display:flex;gap:8px;align-items:center;">
              <button class="primary" id="btn-run" onclick="runAnalysis()">Run Analysis</button>
              <span id="run-status" class="muted"></span>
            </div>
          </section>

          <section class="card" id="results-card" style="display:none;">
            <h2 id="results-title">Results</h2>
            <div class="result-grid">
              <div>
                <h3>Store Profile</h3>
                <div class="result-panel" id="profile-panel">
                  <div class="loading" id="profile-loading"><div class="spinner"></div><div>Analyzing store...</div></div>
                  <pre id="profile-content" style="display:none;"></pre>
                  <div id="profile-error" class="muted" style="display:none;color:#be3b3b;"></div>
                </div>
              </div>
              <div>
                <h3>Competitor Analysis</h3>
                <div class="result-panel" id="competitor-panel">
                  <div class="loading" id="competitor-loading"><div class="spinner"></div><div>Researching competitors...</div></div>
                  <div id="competitor-content" style="display:none;"></div>
                  <div id="competitor-error" class="muted" style="display:none;color:#be3b3b;"></div>
                </div>
              </div>
            </div>
          </section>

          <section class="card">
            <h2>History</h2>
            <div id="history-list" class="muted">Loading...</div>
          </section>
        </main>

        <script>
          async function api(path, options = {}) {
            const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
            if (!res.ok) throw new Error(await res.text());
            return res.json();
          }

          async function runAnalysis() {
            const storeUrl = document.getElementById("store-url").value.trim();
            if (!storeUrl) { alert("Please enter a store URL."); return; }

            const btn = document.getElementById("btn-run");
            const status = document.getElementById("run-status");
            btn.disabled = true;
            status.textContent = "Running...";

            const card = document.getElementById("results-card");
            card.style.display = "block";
            document.getElementById("results-title").textContent = "Results: " + storeUrl;

            document.getElementById("profile-loading").style.display = "block";
            document.getElementById("profile-content").style.display = "none";
            document.getElementById("profile-error").style.display = "none";
            document.getElementById("competitor-loading").style.display = "block";
            document.getElementById("competitor-content").style.display = "none";
            document.getElementById("competitor-error").style.display = "none";

            try {
              const data = await api("/shop-analysis/run", {
                method: "POST",
                body: JSON.stringify({
                  store_url: storeUrl,
                  description: document.getElementById("store-description").value.trim(),
                  industry_code: document.getElementById("industry-code").value.trim() || "general",
                }),
              });

              document.getElementById("profile-loading").style.display = "none";
              if (data.profile) {
                document.getElementById("profile-content").style.display = "block";
                document.getElementById("profile-content").textContent = JSON.stringify(data.profile.content, null, 2);
              } else {
                document.getElementById("profile-error").style.display = "block";
                document.getElementById("profile-error").textContent = data.error_message || "Profile analysis failed.";
              }

              document.getElementById("competitor-loading").style.display = "none";
              if (data.competitor_analysis) {
                document.getElementById("competitor-content").style.display = "block";
                const report = data.competitor_analysis.content.report || "";
                document.getElementById("competitor-content").innerHTML = report
                  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
                  .replace(/\\n/g, "<br>")
                  .replace(/## (.+)/g, "<h3>$1</h3>")
                  .replace(/### (.+)/g, "<h4>$1</h4>")
                  .replace(/\\*\\*(.+?)\\*\\*/g, "<b>$1</b>");
              } else {
                document.getElementById("competitor-error").style.display = "block";
                document.getElementById("competitor-error").textContent = data.error_message || "Competitor analysis failed.";
              }

              status.textContent = "Done!";
              loadHistory();
            } catch (err) {
              status.textContent = "Error: " + err.message;
              document.getElementById("profile-loading").style.display = "none";
              document.getElementById("competitor-loading").style.display = "none";
            } finally {
              btn.disabled = false;
            }
          }

          async function loadHistory() {
            try {
              const data = await api("/shop-analysis/history");
              const list = document.getElementById("history-list");
              if (!data.items.length) {
                list.innerHTML = '<div class="muted">No analyses yet.</div>';
                return;
              }
              list.innerHTML = data.items.map(item => {
                const badgeClass = item.status === "completed" ? "completed" : "failed";
                const dt = new Date(item.created_at);
                const timeStr = String(dt.getMonth()+1).padStart(2,'0') + "-" +
                  String(dt.getDate()).padStart(2,'0') + " " +
                  String(dt.getHours()).padStart(2,'0') + ":" +
                  String(dt.getMinutes()).padStart(2,'0');
                return '<div class="history-item">'
                  + '<div><b>' + item.store_url.replace(/</g, "&lt;") + '</b>'
                  + ' <span class="status-badge ' + badgeClass + '">' + item.source_type + '</span>'
                  + '<br><span class="muted">' + (item.summary || '').replace(/</g, "&lt;").substring(0, 100) + '</span></div>'
                  + '<div class="muted">' + timeStr + '</div>'
                  + '</div>';
              }).join("");
            } catch (err) {
              document.getElementById("history-list").innerHTML = '<div class="muted">Failed to load history.</div>';
            }
          }

          document.addEventListener("DOMContentLoaded", loadHistory);
        </script>
      </body>
    </html>
    """


def _dashboard_html() -> str:
    """Render the dashboard page using the new app/dashboard/ module."""
    from app.dashboard.create_run import CREATE_RUN_HTML, CREATE_RUN_JS
    from app.dashboard.layout import render_dashboard
    return render_dashboard(CREATE_RUN_HTML, CREATE_RUN_JS + _dashboard_shared_js())



def _personas_dashboard_html() -> str:
    return """
    <html>
      <head>
        <title>Crispy Personas</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>
          :root {
            --bg: #f4f7f2;
            --bg-alt: #e8f2f8;
            --card: rgba(255, 255, 255, 0.92);
            --text: #183329;
            --muted: #5e6e66;
            --line: #d8e5dc;
            --accent: #1f7a62;
            --accent-soft: #e7f6ef;
            --radius: 16px;
            --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
          }
          * { box-sizing: border-box; }
          body {
            margin: 0;
            color: var(--text);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
            background:
              radial-gradient(circle at 10% -20%, #d9ede6 0%, transparent 40%),
              radial-gradient(circle at 90% -20%, #d8e9f6 0%, transparent 42%),
              linear-gradient(180deg, var(--bg-alt), var(--bg) 30%);
          }
          .app-shell { width: min(1460px, calc(100% - 24px)); margin: 20px auto 30px auto; }
          .hero {
            display:flex;
            justify-content: space-between;
            align-items: flex-end;
            gap: 12px;
            margin-bottom: 14px;
          }
          h1, h2, h3 { margin: 0; line-height: 1.25; }
          h1 { font-size: 28px; letter-spacing: -0.02em; }
          h2 { font-size: 20px; margin-bottom: 10px; }
          .subtitle { margin-top: 6px; color: var(--muted); font-size: 14px; }
          .card {
            border: 1px solid var(--line);
            border-radius: var(--radius);
            padding: 14px;
            background: var(--card);
            box-shadow: 0 8px 24px rgba(30, 62, 50, 0.07);
            backdrop-filter: blur(4px);
          }
          .nav-link {
            border: 1px solid var(--line);
            background: #fff;
            padding: 8px 12px;
            border-radius: 999px;
            font-size: 13px;
            font-weight: 600;
            color: #135f4c;
            text-decoration: none;
            white-space: nowrap;
          }
          .filters { margin-bottom: 12px; }
          .filters-row {
            display: grid;
            grid-template-columns: 1.4fr 1fr;
            gap: 10px;
          }
          label { display: block; font-size: 12px; color: #3f5c52; margin-bottom: 5px; font-weight: 600; }
          input, select, textarea {
            width: 100%;
            padding: 9px 10px;
            border-radius: 10px;
            border: 1px solid #c8d8ce;
            background: #fff;
            color: var(--text);
            font-size: 14px;
          }
          input:focus, select:focus, textarea:focus {
            outline: none;
            border-color: var(--accent);
            box-shadow: 0 0 0 3px rgba(31, 122, 98, 0.16);
          }
          .workspace {
            display: grid;
            grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr);
            gap: 14px;
            align-items: start;
          }
          .board {
            display: grid;
            grid-auto-flow: column;
            grid-auto-columns: minmax(240px, 1fr);
            gap: 12px;
            overflow-x: auto;
            padding-bottom: 6px;
          }
          .board-column {
            border: 1px solid #dce9df;
            border-radius: 12px;
            background: #f8fbf9;
            padding: 10px;
            min-height: 380px;
          }
          .column-head {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
            gap: 6px;
          }
          .column-title {
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            color: #356353;
            font-weight: 700;
          }
          .count-pill {
            border: 1px solid #c8ddd0;
            border-radius: 999px;
            background: #f2faf5;
            color: #356353;
            font-size: 11px;
            padding: 1px 8px;
            font-weight: 700;
          }
          .column-list {
            display: flex;
            flex-direction: column;
            gap: 8px;
          }
          .persona-card {
            border: 1px solid #cfe0d5;
            border-radius: 10px;
            background: #fff;
            width: 100%;
            text-align: left;
            padding: 10px;
            cursor: pointer;
          }
          .persona-card:hover { background: #f7fcf9; }
          .persona-card.active {
            border-color: #7cb89f;
            box-shadow: 0 0 0 2px rgba(31, 122, 98, 0.12);
            background: var(--accent-soft);
          }
          .persona-name { font-weight: 700; margin-bottom: 3px; color: #1d4a3c; }
          .persona-agent {
            font-size: 11px;
            color: #5b6e65;
            font-family: var(--mono);
            margin-bottom: 4px;
          }
          .persona-role {
            font-size: 12px;
            color: #3d5a50;
            line-height: 1.35;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
          }
          .empty {
            border: 1px dashed #c8dacd;
            border-radius: 10px;
            padding: 14px;
            text-align: center;
            color: var(--muted);
            background: #f9fcfa;
            font-size: 13px;
          }
          .editor-meta { color: var(--muted); font-size: 12px; margin-bottom: 8px; line-height: 1.5; }
          .editor-actions {
            margin-top: 10px;
            display: flex;
            gap: 8px;
            align-items: center;
            flex-wrap: wrap;
          }
          button {
            padding: 8px 12px;
            border-radius: 10px;
            border: 1px solid #bfd0c5;
            background: #f4faf5;
            color: #20473a;
            font-weight: 600;
            cursor: pointer;
          }
          button:hover { background: #eaf6ee; }
          button.primary {
            background: linear-gradient(135deg, var(--accent), #2d9d79);
            border-color: #1b735b;
            color: #fff;
          }
          button:disabled {
            cursor: not-allowed;
            opacity: 0.6;
          }
          .status-msg { font-size: 13px; font-weight: 600; }
          .status-ok { color: #1f7a62; }
          .status-error { color: #b64040; }
          .status-warn { color: #8a6a28; font-weight: 500; }
          @media (max-width: 1120px) {
            .workspace { grid-template-columns: 1fr; }
            .board { grid-auto-columns: minmax(220px, 1fr); }
          }
          @media (max-width: 860px) {
            .app-shell { width: calc(100% - 12px); margin-top: 10px; }
            .hero { flex-direction: column; align-items: flex-start; }
            .filters-row { grid-template-columns: 1fr; }
          }
        </style>
      </head>
      <body>
        <main class="app-shell">
          <header class="hero">
            <div>
              <h1>Persona Board</h1>
              <div class="subtitle">Notion-style board for agent persona tuning and versioned prompt edits.</div>
            </div>
            <a class="nav-link" href="/dashboard">Back to Dashboard</a>
          </header>

          <section class="card filters">
            <div class="filters-row">
              <div>
                <label>Search Persona</label>
                <input id="persona-search" placeholder="Search by display name, agent name, role, stage" />
              </div>
              <div>
                <label>Stage Filter</label>
                <select id="stage-filter">
                  <option value="">All stages</option>
                </select>
              </div>
            </div>
          </section>

          <div class="workspace">
            <section class="card">
              <h2>Board</h2>
              <div id="persona-board" class="board"></div>
            </section>
            <section class="card">
              <h2 id="editor-title">Select a persona card</h2>
              <div id="editor-meta" class="editor-meta">Click any card to load persona markdown.</div>
              <textarea id="persona-content" rows="22" placeholder="Select a persona from board first." disabled></textarea>
              <div class="editor-actions">
                <button id="persona-save" class="primary" onclick="savePersona()" disabled>Save Persona</button>
                <span id="save-msg" class="status-msg"></span>
              </div>
            </section>
          </div>
        </main>
        <script>
          let personas = [];
          let currentPersona = null;
          let currentVersion = null;
          let currentSourcePath = "";

          const stageLabels = {
            manager: "Manager",
            research: "Research",
            ideation: "Ideation",
            generation: "Generation",
            scoring: "Scoring",
            global: "Global",
            other: "Other",
          };
          const preferredStages = ["manager", "research", "ideation", "generation", "scoring", "global"];

          function esc(v){
            return String(v ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;");
          }
          function toStage(v){
            const stage = String(v || "").trim().toLowerCase();
            return stage || "other";
          }
          function stageLabel(stage){
            return stageLabels[stage] || stage.replaceAll("_", " ");
          }
          function stageOrder(rows){
            const stages = Array.from(new Set(rows.map((p) => toStage(p.stage))));
            const known = preferredStages.filter((s) => stages.includes(s));
            const rest = stages.filter((s) => !known.includes(s)).sort((a, b) => a.localeCompare(b));
            return [...known, ...rest];
          }
          function grouped(rows){
            const byStage = {};
            stageOrder(rows).forEach((stage) => { byStage[stage] = []; });
            rows.forEach((item) => {
              const stage = toStage(item.stage);
              if (!byStage[stage]) byStage[stage] = [];
              byStage[stage].push(item);
            });
            Object.values(byStage).forEach((items) => {
              items.sort((a, b) => (a.order ?? 9999) - (b.order ?? 9999));
            });
            return byStage;
          }
          async function api(path, options = {}) {
            const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
            if (!res.ok) throw new Error(await res.text());
            return res.json();
          }
          function updateStageFilterOptions(rows){
            const sel = document.getElementById("stage-filter");
            const prev = sel.value;
            const stages = stageOrder(rows);
            sel.innerHTML = '<option value="">All stages</option>';
            stages.forEach((stage) => {
              const opt = document.createElement("option");
              opt.value = stage;
              opt.textContent = stageLabel(stage);
              sel.appendChild(opt);
            });
            sel.value = stages.includes(prev) ? prev : "";
          }
          function renderBoard(){
            const search = document.getElementById("persona-search").value.trim().toLowerCase();
            const stageFilter = document.getElementById("stage-filter").value;
            const filtered = personas.filter((p) => {
              const hit = !search || [
                p.display_name,
                p.agent_name,
                p.stage,
                p.role,
              ].join(" ").toLowerCase().includes(search);
              const stageHit = !stageFilter || toStage(p.stage) === stageFilter;
              return hit && stageHit;
            });
            const board = document.getElementById("persona-board");
            if (!filtered.length) {
              board.innerHTML = '<div class="empty">No personas match current filters.</div>';
              return;
            }
            const byStage = grouped(filtered);
            const columns = Object.entries(byStage)
              .map(([stage, items]) => {
                const cards = items
                  .map((p) => `
                    <button class="persona-card ${currentPersona === p.agent_name ? "active" : ""}" onclick="openPersona('${esc(p.agent_name)}')">
                      <div class="persona-name">${esc(p.display_name || p.agent_name)}</div>
                      <div class="persona-agent">${esc(p.agent_name)}</div>
                      <div class="persona-role">${esc(p.role || "-")}</div>
                    </button>
                  `)
                  .join("");
                return `
                  <article class="board-column">
                    <div class="column-head">
                      <div class="column-title">${esc(stageLabel(stage))}</div>
                      <span class="count-pill">${items.length}</span>
                    </div>
                    <div class="column-list">${cards}</div>
                  </article>
                `;
              })
              .join("");
            board.innerHTML = columns;
          }
          async function openPersona(agentName){
            try {
              const p = await api(`/personas/${agentName}`);
              currentPersona = p.agent_name;
              currentVersion = p.version;
              currentSourcePath = p.source_path || "";
              document.getElementById("editor-title").textContent = `${p.display_name} (${p.stage})`;
              document.getElementById("editor-meta").innerHTML =
                `agent: <code>${esc(p.agent_name)}</code> | version: <code>${esc(p.version)}</code><br/>source: <code>${esc(currentSourcePath)}</code>`;
              const area = document.getElementById("persona-content");
              area.disabled = false;
              area.value = p.content || "";
              document.getElementById("persona-save").disabled = false;
              document.getElementById("save-msg").textContent = "";
              document.getElementById("save-msg").className = "status-msg";
              renderBoard();
              const target = `/dashboard/personas?agent=${encodeURIComponent(agentName)}`;
              if (window.location.pathname + window.location.search !== target) {
                history.replaceState({}, "", target);
              }
            } catch (err) {
              const msg = document.getElementById("save-msg");
              msg.className = "status-msg status-error";
              msg.textContent = `Load failed: ${err.message || err}`;
            }
          }
          async function savePersona(){
            if (!currentPersona) return;
            const msg = document.getElementById("save-msg");
            msg.className = "status-msg";
            msg.textContent = "Saving...";
            try {
              const content = document.getElementById("persona-content").value;
              const updated = await api(`/personas/${currentPersona}`, {
                method: "PATCH",
                body: JSON.stringify({ content, changed_by: "dashboard_personas_ui" }),
              });
              currentVersion = updated.version;
              currentSourcePath = updated.source_path || currentSourcePath;
              document.getElementById("editor-meta").innerHTML =
                `agent: <code>${esc(updated.agent_name)}</code> | version: <code>${esc(updated.version)}</code><br/>source: <code>${esc(currentSourcePath)}</code>`;
              msg.className = "status-msg status-ok";
              msg.textContent = `Saved ${updated.agent_name} (v${updated.version})`;
            } catch (err) {
              msg.className = "status-msg status-error";
              msg.textContent = `Save failed: ${err.message || err}`;
            }
          }
          async function init(){
            try {
              personas = await api("/personas");
              updateStageFilterOptions(personas);
              renderBoard();
              const params = new URLSearchParams(window.location.search);
              const target = params.get("agent");
              if (target && personas.some((p) => p.agent_name === target)) {
                await openPersona(target);
                return;
              }
              const gm = personas.find((p) => p.agent_name === "gm_orchestrator");
              if (gm) {
                await openPersona(gm.agent_name);
              }
            } catch (err) {
              const board = document.getElementById("persona-board");
              board.innerHTML = `<div class="empty">Failed to load personas: ${esc(err.message || err)}</div>`;
            }
          }
          document.getElementById("persona-search").addEventListener("input", renderBoard);
          document.getElementById("stage-filter").addEventListener("change", renderBoard);
          document.getElementById("persona-content").addEventListener("input", () => {
            if (!currentPersona) return;
            const msg = document.getElementById("save-msg");
            msg.className = "status-msg status-warn";
            msg.textContent = "Unsaved changes";
          });
          document.addEventListener("keydown", (event) => {
            if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
              event.preventDefault();
              savePersona();
            }
          });
          init();
        </script>
      </body>
    </html>
    """


def _agent_api_dashboard_html(personas_json: str, configs_json: str, env_vars_json: str) -> str:
    return f"""
    <html>
      <head>
        <title>Crispy Agent API Configs</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>
          :root {{
            --bg: #f4f7f2;
            --bg-alt: #e8f2f8;
            --card: rgba(255, 255, 255, 0.92);
            --text: #183329;
            --muted: #5e6e66;
            --line: #d8e5dc;
            --accent: #1f7a62;
            --radius: 16px;
            --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
          }}
          * {{ box-sizing: border-box; }}
          body {{
            margin: 0;
            color: var(--text);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
            background:
              radial-gradient(circle at 10% -20%, #d9ede6 0%, transparent 40%),
              radial-gradient(circle at 90% -20%, #d8e9f6 0%, transparent 42%),
              linear-gradient(180deg, var(--bg-alt), var(--bg) 30%);
          }}
          .app-shell {{ width: min(1320px, calc(100% - 24px)); margin: 22px auto 30px auto; }}
          .hero {{
            display:flex;
            justify-content: space-between;
            align-items: flex-end;
            gap: 12px;
            margin-bottom: 14px;
          }}
          .page-actions {{
            display: flex;
            justify-content: flex-end;
            margin-bottom: 10px;
          }}
          h1, h2 {{ margin: 0; line-height: 1.25; }}
          h1 {{ font-size: 27px; letter-spacing: -0.02em; }}
          h2 {{ font-size: 19px; margin-bottom: 10px; }}
          .subtitle {{ margin-top: 6px; color: var(--muted); font-size: 14px; }}
          .muted {{ color: var(--muted); font-size: 12px; }}
          a {{ color: #135f4c; text-decoration: none; }}
          a:hover {{ text-decoration: underline; }}
          .nav-link {{
            border: 1px solid var(--line);
            background: #fff;
            padding: 8px 12px;
            border-radius: 999px;
            font-size: 13px;
            font-weight: 600;
          }}
          .card {{
            border: 1px solid var(--line);
            border-radius: var(--radius);
            padding: 16px;
            background: var(--card);
            box-shadow: 0 8px 24px rgba(30, 62, 50, 0.07);
            backdrop-filter: blur(4px);
          }}
          .secondary-btn {{
            background: #f8fbf8;
          }}
          .toast-wrap {{
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 9999;
            pointer-events: none;
          }}
          .toast {{
            min-width: 180px;
            max-width: 320px;
            padding: 10px 12px;
            border-radius: 10px;
            border: 1px solid #9fd0b7;
            background: #ecfaf2;
            color: #1d4a3b;
            box-shadow: 0 8px 20px rgba(28, 68, 52, 0.16);
            font-size: 13px;
            font-weight: 700;
            opacity: 0;
            transform: translateY(-6px);
            transition: opacity 180ms ease, transform 180ms ease;
          }}
          .toast.show {{
            opacity: 1;
            transform: translateY(0);
          }}
          .table-wrap {{ overflow: auto; border: 1px solid var(--line); border-radius: 12px; }}
          table {{ width: 100%; border-collapse: collapse; font-size: 13px; min-width: 920px; }}
          th, td {{ border-bottom: 1px solid #e8eee8; padding: 9px 10px; text-align: left; vertical-align: top; }}
          thead th {{ background: #f8fbf8; font-weight: 700; color: #295345; }}
          .advanced-col {{
            min-width: 120px;
            max-width: 220px;
            opacity: 1;
            white-space: nowrap;
            overflow: hidden;
            transition: min-width 220ms ease, max-width 220ms ease, padding 180ms ease, opacity 160ms ease;
          }}
          table.advanced-collapsed .advanced-col {{
            min-width: 0;
            max-width: 0;
            padding-left: 0;
            padding-right: 0;
            opacity: 0;
          }}
          input, select {{
            width: 100%;
            padding: 8px 9px;
            border-radius: 9px;
            border: 1px solid #c8d8ce;
            box-sizing: border-box;
            background: #fff;
            color: var(--text);
          }}
          input:focus, select:focus {{
            outline: none;
            border-color: var(--accent);
            box-shadow: 0 0 0 3px rgba(31, 122, 98, 0.16);
          }}
          button {{
            padding: 7px 10px;
            border-radius: 10px;
            border: 1px solid #bfd0c5;
            background: #f4faf5;
            color: #20473a;
            font-weight: 600;
            cursor: pointer;
          }}
          button:hover {{ background: #eaf6ee; }}
          .panel {{ margin-top: 16px; }}
          .row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
          .badge {{
            display: inline-block;
            border: 1px solid #c6dbc5;
            background: #f5faf5;
            border-radius: 999px;
            font-size: 11px;
            font-weight: 600;
            padding: 2px 8px;
          }}
          .badge-missing {{ border-color: #e2c8c8; background: #fff5f5; color: #925454; }}
          code {{ font-family: var(--mono); font-size: 12px; }}
          @media (max-width: 860px) {{
            .app-shell {{ width: calc(100% - 12px); margin-top: 10px; }}
            .hero {{ flex-direction: column; align-items: flex-start; }}
            .row {{ grid-template-columns: 1fr; }}
          }}
        </style>
      </head>
      <body>
        <div class="toast-wrap">
          <div id="save-toast" class="toast">Saved</div>
        </div>
        <main class="app-shell">
          <header class="hero">
            <div>
              <h1>Agent API Configs</h1>
              <div class="subtitle">Fallback rule: if agent config missing, use <b>default</b>.</div>
              <div class="subtitle">Security: only env var names are stored. Prefix required: <b>{API_KEY_ENV_PREFIX}</b>.</div>
              <div class="subtitle">Multimodal agents expose modality-specific rows for image and video generation.</div>
            </div>
            <a class="nav-link" href="/dashboard">Back to Dashboard</a>
          </header>
          <div class="page-actions">
            <button id="toggle-advanced-cols" class="secondary-btn" onclick="toggleAdvancedCols()">Show Advanced Columns</button>
          </div>
          <section class="card">
            <div class="table-wrap">
              <table id="cfg-table" class="advanced-collapsed">
                <thead><tr><th>Agent</th><th>Provider</th><th>Model</th><th>Base URL</th><th>API Key Env</th><th>Thinking</th><th class="advanced-col">Stream</th><th class="advanced-col">Budget</th><th class="advanced-col">Max Tokens</th><th class="advanced-col">Timeout</th><th>Env Status</th><th>Action</th></tr></thead>
                <tbody id="cfg-body"></tbody>
              </table>
            </div>
          </section>
        </main>
        <script>
          const personas = {personas_json};
          const existing = {configs_json};
          let envVars = {env_vars_json};
          let advancedColsVisible = false;
          let toastTimer = null;
          const byAgent = Object.fromEntries(existing.map(c => [c.agent_name, c]));
          const baseRows = [{{ agent_name: "default", display_name: "Default Fallback", stage: "global" }}, ...personas];
          const shopAnalysisAgents = new Set(["shop_analyst"]);
          const pipelinePersonas = baseRows.filter((r) => !shopAnalysisAgents.has(r.agent_name));
          const rows = pipelinePersonas.flatMap((r) => {{
            const title = (r.display_name || r.agent_name);
            if (r.agent_name === "copy_image_agent") {{
              return [
                {{ row_key: "copy_image_agent__text", agent_name: "copy_image_agent", mode: "text", title: "Copy Image Agent - Text", source: "copy_image_agent" }},
                {{ row_key: "copy_image_agent__image", agent_name: "copy_image_agent", mode: "image", title: "Copy Image Agent - Image", source: "copy_image_agent" }},
              ];
            }}
            if (r.agent_name === "video_generation_agent") {{
              return [
                {{ row_key: "video_generation_agent__text", agent_name: "video_generation_agent", mode: "text", title: "Video Generation Agent - Text", source: "video_generation_agent" }},
                {{ row_key: "video_generation_agent__video", agent_name: "video_generation_agent", mode: "video", title: "Video Generation Agent - Video", source: "video_generation_agent" }},
              ];
            }}
            return [{{ row_key: `${{r.agent_name}}__text`, agent_name: r.agent_name, mode: "text", title, source: r.agent_name }}];
          }});
          // Append Shop Analysis section at the bottom
          rows.push(
            {{ row_key: "__divider_shop__", agent_name: "__divider__", mode: "text", title: "divider", source: "divider", isDivider: true }},
            {{ row_key: "shop_analyst__text", agent_name: "shop_analyst", mode: "text", title: "Shop Analyst - LLM", source: "shop_analyst" }},
            {{ row_key: "shop_analyst__tavily", agent_name: "shop_analyst", mode: "tavily", title: "Shop Analyst - Tavily", source: "shop_analyst" }},
            {{ row_key: "shop_analyst__firecrawl", agent_name: "shop_analyst", mode: "firecrawl", title: "Shop Analyst - Firecrawl", source: "shop_analyst" }},
          );
          async function api(path, options = {{}}) {{
            const res = await fetch(path, {{ headers: {{ "Content-Type": "application/json" }}, ...options }});
            if (!res.ok) throw new Error(await res.text());
            return res.json();
          }}
          function envOptions(selected) {{
            const base = ['<option value="">(none)</option>'];
            const names = [...envVars];
            if (selected && !names.includes(selected)) names.unshift(selected);
            names.forEach((name) => {{ base.push(`<option value="${{name}}"${{selected===name?" selected":""}}>${{name}}</option>`); }});
            return base.join("");
          }}
          function applyAdvancedColsVisibility() {{
            const table = document.getElementById("cfg-table");
            if (table) {{
              table.classList.toggle("advanced-collapsed", !advancedColsVisible);
            }}
            const btn = document.getElementById("toggle-advanced-cols");
            btn.textContent = advancedColsVisible ? "Hide Advanced Columns" : "Show Advanced Columns";
          }}
          function toggleAdvancedCols() {{
            advancedColsVisible = !advancedColsVisible;
            applyAdvancedColsVisibility();
          }}
          function showSaveToast(message) {{
            const toast = document.getElementById("save-toast");
            if (!toast) return;
            toast.textContent = message || "Saved";
            toast.classList.add("show");
            if (toastTimer) clearTimeout(toastTimer);
            toastTimer = setTimeout(() => {{
              toast.classList.remove("show");
            }}, 1700);
          }}
          function render() {{
            const body = document.getElementById("cfg-body");
            body.innerHTML = "";
            rows.forEach((r) => {{
              if (r.isDivider) {{
                const tr = document.createElement("tr");
                tr.innerHTML = '<td colspan="12" style="padding:8px 10px;background:#f0f4f2;border-bottom:2px solid var(--accent);font-weight:700;font-size:12px;color:var(--accent);">Shop Analysis Agents</td>';
                body.appendChild(tr);
                return;
              }}
              const cfg = byAgent[r.agent_name] || {{}};
              const isSearchTool = (r.mode === "tavily" || r.mode === "firecrawl");
              const provider = r.mode === "text" ? (cfg.provider_name || "") : (r.mode === "image" ? (cfg.image_provider_name || "") : (cfg.video_provider_name || ""));
              const model = r.mode === "text" ? (cfg.model_name || "") : (r.mode === "image" ? (cfg.image_model_name || "") : (cfg.video_model_name || ""));
              const baseUrl = r.mode === "text" ? (cfg.api_base_url || "") : (r.mode === "image" ? (cfg.image_api_base_url || "") : (cfg.video_api_base_url || ""));
              const keyEnv = r.mode === "tavily" ? (cfg.extra?.tavily_config?.api_key_env || "")
                : r.mode === "firecrawl" ? (cfg.extra?.firecrawl_config?.api_key_env || "")
                : r.mode === "text" ? (cfg.api_key_env || "")
                : r.mode === "image" ? (cfg.image_api_key_env || "")
                : (cfg.video_api_key_env || "");
              const keyFound = r.mode === "tavily" ? cfg.tavily_api_key_available
                : r.mode === "firecrawl" ? cfg.firecrawl_api_key_available
                : r.mode === "text" ? cfg.api_key_available
                : r.mode === "image" ? cfg.image_api_key_available
                : cfg.video_api_key_available;
              const thinkingMode = r.mode === "text" ? (cfg.thinking_mode || "auto") : "";
              const thinkingBudget = r.mode === "text" ? (cfg.thinking_budget_tokens || "") : "";
              const maxTokens = r.mode === "text" ? (cfg.max_output_tokens || "") : "";
              const requestTimeout = r.mode === "text" ? (cfg.request_timeout_seconds || "") : "";
              const streamingEnabled = r.mode === "text" ? Boolean(cfg.streaming_enabled) : false;
              const tr = document.createElement("tr");
              const envStatus = keyEnv
                ? (keyFound ? '<span class="badge">found</span>' : '<span class="badge badge-missing">missing</span>')
                : '<span class="muted">-</span>';
              const providerCell = isSearchTool ? '<td class="muted">-</td>'
                : `<td><input id="p-${{r.row_key}}" value="${{provider}}" /></td>`;
              const modelCell = isSearchTool ? '<td class="muted">-</td>'
                : `<td><input id="m-${{r.row_key}}" value="${{model}}" /></td>`;
              const baseUrlCell = isSearchTool ? '<td class="muted">-</td>'
                : `<td><input id="b-${{r.row_key}}" value="${{baseUrl}}" /></td>`;
              const thinkingCell = (r.mode === "text") ? `<td><select id="t-${{r.row_key}}"><option value="auto"${{thinkingMode==="auto"?" selected":""}}>auto</option><option value="enabled"${{thinkingMode==="enabled"?" selected":""}}>enabled</option><option value="disabled"${{thinkingMode==="disabled"?" selected":""}}>disabled</option></select></td>`
                : '<td class="muted">-</td>';
              const streamCell = (r.mode === "text") ? `<td class="advanced-col"><input id="s-${{r.row_key}}" type="checkbox"${{streamingEnabled ? " checked" : ""}} /></td>`
                : '<td class="advanced-col muted">-</td>';
              const budgetCell = (r.mode === "text") ? `<td class="advanced-col"><input id="g-${{r.row_key}}" value="${{thinkingBudget}}" placeholder="optional" /></td>`
                : '<td class="advanced-col muted">-</td>';
              const maxTokensCell = (r.mode === "text") ? `<td class="advanced-col"><input id="o-${{r.row_key}}" value="${{maxTokens}}" placeholder="1200" /></td>`
                : '<td class="advanced-col muted">-</td>';
              const timeoutCell = (r.mode === "text") ? `<td class="advanced-col"><input id="x-${{r.row_key}}" value="${{requestTimeout}}" placeholder="90" /></td>`
                : '<td class="advanced-col muted">-</td>';
              tr.innerHTML = `
                <td>${{r.title}}<div class="muted">${{r.source}}</div></td>
                ${{providerCell}}
                ${{modelCell}}
                ${{baseUrlCell}}
                <td><select id="k-${{r.row_key}}">${{envOptions(keyEnv)}}</select></td>
                ${{thinkingCell}}
                ${{streamCell}}
                ${{budgetCell}}
                ${{maxTokensCell}}
                ${{timeoutCell}}
                <td>${{envStatus}}</td>
                <td><button onclick="save('${{r.row_key}}')">Save</button></td>`;
              body.appendChild(tr);
            }});
            applyAdvancedColsVisibility();
          }}
          async function save(rowKey) {{
            const row = rows.find((r) => r.row_key === rowKey);
            if (!row) return;
            const api_key_env = document.getElementById(`k-${{rowKey}}`).value || null;
            // Build extra config based on row mode
            let mergedExtra = {{ ...(byAgent[row.agent_name]?.extra || {{}}) }};
            if (row.mode === "tavily") {{
              mergedExtra.tavily_config = {{ api_key_env }};
            }} else if (row.mode === "firecrawl") {{
              mergedExtra.firecrawl_config = {{ api_key_env }};
            }}
            let payload = {{}};
            if (row.mode === "text") {{
              const provider_name = document.getElementById(`p-${{rowKey}}`).value || null;
              const model_name = document.getElementById(`m-${{rowKey}}`).value || null;
              const api_base_url = document.getElementById(`b-${{rowKey}}`).value || null;
              const max_output_tokens = document.getElementById(`o-${{rowKey}}`).value;
              const thinking_budget_tokens = document.getElementById(`g-${{rowKey}}`).value;
              const request_timeout_seconds = document.getElementById(`x-${{rowKey}}`).value;
              payload = {{
                provider_name,
                model_name,
                api_base_url,
                api_key_env,
                thinking_mode: document.getElementById(`t-${{rowKey}}`).value,
                thinking_budget_tokens: thinking_budget_tokens ? Number(thinking_budget_tokens) : null,
                max_output_tokens: max_output_tokens ? Number(max_output_tokens) : null,
                request_timeout_seconds: request_timeout_seconds ? Number(request_timeout_seconds) : null,
                streaming_enabled: document.getElementById(`s-${{rowKey}}`).checked,
                extra: mergedExtra
              }};
            }} else if (row.mode === "image") {{
              const provider_name = document.getElementById(`p-${{rowKey}}`).value || null;
              const model_name = document.getElementById(`m-${{rowKey}}`).value || null;
              const api_base_url = document.getElementById(`b-${{rowKey}}`).value || null;
              payload = {{
                image_provider_name: provider_name,
                image_model_name: model_name,
                image_api_base_url: api_base_url,
                image_api_key_env: api_key_env
              }};
            }} else if (row.mode === "video") {{
              const provider_name = document.getElementById(`p-${{rowKey}}`).value || null;
              const model_name = document.getElementById(`m-${{rowKey}}`).value || null;
              const api_base_url = document.getElementById(`b-${{rowKey}}`).value || null;
              payload = {{
                video_provider_name: provider_name,
                video_model_name: model_name,
                video_api_base_url: api_base_url,
                video_api_key_env: api_key_env
              }};
            }} else if (row.mode === "tavily" || row.mode === "firecrawl") {{
              payload = {{ extra: mergedExtra }};
            }}
            byAgent[row.agent_name] = await api(`/agent-configs/${{row.agent_name}}`, {{ method: "PATCH", body: JSON.stringify(payload) }});
            render();
            showSaveToast(`Saved: ${{row.title}}`);
          }}
          async function init() {{
            try {{ envVars = await api("/agent-configs/env-vars"); }} catch (_err) {{}}
            render();
          }}
          init();
        </script>
      </body>
    </html>
    """


def _assets_dashboard_html() -> str:
    return """
    <html>
      <head>
        <title>Crispy Asset Library</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>
          :root {
            --bg: #f4f7f2;
            --bg-alt: #e8f2f8;
            --card: rgba(255, 255, 255, 0.92);
            --text: #183329;
            --muted: #5e6e66;
            --line: #d8e5dc;
            --accent: #1f7a62;
            --radius: 16px;
            --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
          }
          * { box-sizing: border-box; }
          body {
            margin: 0;
            color: var(--text);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
            background:
              radial-gradient(circle at 10% -20%, #d9ede6 0%, transparent 40%),
              radial-gradient(circle at 90% -20%, #d8e9f6 0%, transparent 42%),
              linear-gradient(180deg, var(--bg-alt), var(--bg) 30%);
          }
          .app-shell { width: min(1380px, calc(100% - 24px)); margin: 22px auto 30px auto; }
          .card {
            border: 1px solid var(--line);
            border-radius: var(--radius);
            padding: 16px;
            background: var(--card);
            margin-bottom: 14px;
            box-shadow: 0 8px 24px rgba(30, 62, 50, 0.07);
            backdrop-filter: blur(4px);
          }
          h1 { margin: 0; font-size: 27px; letter-spacing: -0.02em; line-height: 1.2; }
          .subtitle { margin-top: 6px; color: var(--muted); font-size: 14px; }
          .filters { display:grid; grid-template-columns: 2fr 1fr 1fr 1fr 1fr 1fr; gap:10px; align-items:end; }
          .filters-bottom {
            display:flex;
            gap:10px;
            align-items:end;
            margin-top:10px;
            flex-wrap: wrap;
          }
          .grid { display:grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap:12px; }
          .asset-card {
            border:1px solid #dce8df;
            border-radius:12px;
            padding:10px;
            background:#fff;
            box-shadow: 0 4px 14px rgba(32, 75, 57, 0.04);
          }
          .asset-card:hover { transform: translateY(-1px); transition: transform 160ms ease; }
          input, select {
            width: 100%;
            padding: 9px 10px;
            border-radius: 10px;
            border: 1px solid #c8d8ce;
            box-sizing: border-box;
            background: #fff;
            color: var(--text);
          }
          input:focus, select:focus {
            outline: none;
            border-color: var(--accent);
            box-shadow: 0 0 0 3px rgba(31, 122, 98, 0.16);
          }
          button {
            padding: 8px 12px;
            border-radius: 10px;
            border: 1px solid #bfd0c5;
            background: #f4faf5;
            color: #20473a;
            font-weight: 600;
            cursor: pointer;
          }
          button:hover { background: #eaf6ee; }
          .muted { color: var(--muted); font-size: 12px; }
          .img-preview {
            width: 100%;
            border-radius: 10px;
            border: 1px solid #dce7e1;
            object-fit: contain;
            max-height: 360px;
            background:#f2f5fa;
          }
          .media-preview {
            width: 100%;
            border-radius: 10px;
            border: 1px solid #dce7e1;
            background:#f2f5fa;
            display:block;
          }
          .media-preview.image {
            object-fit: contain;
            max-height: 420px;
          }
          .media-preview.video {
            aspect-ratio: 9 / 16;
            max-height: 420px;
            object-fit: contain;
            background:#050807;
          }
          .toolbar {
            display:flex;
            justify-content:space-between;
            align-items:flex-end;
            margin-bottom:12px;
            gap: 12px;
          }
          .nav-link {
            border: 1px solid var(--line);
            background: #fff;
            padding: 8px 12px;
            border-radius: 999px;
            font-size: 13px;
            font-weight: 600;
            color: #135f4c;
            text-decoration: none;
            white-space: nowrap;
          }
          .pill {
            display:inline-block;
            padding:2px 8px;
            border-radius:20px;
            font-size:12px;
            border:1px solid #c9ddd1;
            background: #f7fcf8;
            margin-right:6px;
          }
          .stats-line { font-family: var(--mono); }
          .empty {
            grid-column: 1 / -1;
            border: 1px dashed #c8dacd;
            border-radius: 12px;
            padding: 18px;
            text-align: center;
            color: var(--muted);
            background: #f8fcfa;
          }
          @media (max-width: 1040px) {
            .filters { grid-template-columns: 1fr 1fr; }
          }
          @media (max-width: 860px) {
            .app-shell { width: calc(100% - 12px); margin-top: 10px; }
            .filters { grid-template-columns: 1fr; }
            .toolbar { flex-direction: column; align-items: flex-start; }
          }
        </style>
      </head>
      <body>
        <main class="app-shell">
          <div class="toolbar">
            <div>
              <h1>Asset Library</h1>
              <div class="subtitle">Browse generated outputs across runs, modes, and channels.</div>
            </div>
            <a class="nav-link" href="/dashboard">Back to Dashboard</a>
          </div>
          <section class="card">
            <div class="filters">
              <div><label>Search</label><input id="q" placeholder="run id / copy text / filename" /></div>
              <div>
                <label>Type</label>
                <select id="artifact_types">
                  <option value="">All generated</option>
                  <option value="generated_image">generated_image</option>
                  <option value="copy_image_bundle">copy_image_bundle</option>
                  <option value="video_script_pack">video_script_pack</option>
                  <option value="storyboard_pack">storyboard_pack</option>
                  <option value="generated_video">generated_video</option>
                  <option value="video_bundle">video_bundle</option>
                  <option value="visual_quality_report">visual_quality_report</option>
                  <option value="evaluation_selection">evaluation_selection</option>
                </select>
              </div>
            <div>
              <label>Pipeline Mode</label>
              <select id="pipeline_mode">
                <option value="">All</option>
                <option value="copy_image_only">copy_image_only</option>
                <option value="video_only">video_only</option>
                <option value="full_multimodal">full_multimodal</option>
              </select>
            </div>
            <div><label>Product Code</label><input id="product_code" placeholder="DL-001" /></div>
            <div>
              <label>Sort By</label>
              <select id="sort_by">
                <option value="created_at">created_at</option>
                <option value="score">score</option>
                </select>
              </div>
              <div>
                <label>Order</label>
                <select id="sort_order">
                  <option value="desc">desc</option>
                  <option value="asc">asc</option>
                </select>
              </div>
            </div>
            <div class="filters-bottom">
              <div><label>Date From</label><input id="date_from" type="date" /></div>
              <div><label>Date To</label><input id="date_to" type="date" /></div>
              <div><button onclick="refreshAssets()">Apply</button></div>
              <div><button onclick="prevPage()">Prev</button> <button onclick="nextPage()">Next</button></div>
            </div>
          </section>
          <section class="card">
            <div id="stats" class="muted stats-line"></div>
            <div id="asset-grid" class="grid"></div>
          </section>
        </main>
        <script>
          let page = 1;
          let pageSize = 20;
          let total = 0;
          function esc(v){ return String(v ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;");}
          function mediaUrl(path){ return `/media?path=${encodeURIComponent(path || "")}`; }
          function mediaViewUrl(path){ return `/media/view?path=${encodeURIComponent(path || "")}`; }
          function queryString(params){
            const q = new URLSearchParams();
            Object.entries(params).forEach(([k,v]) => {
              if (v === null || v === undefined || v === "") return;
              q.set(k, String(v));
            });
            return q.toString();
          }
          async function refreshAssets() {
            const params = {
              q: document.getElementById("q").value,
              artifact_types: document.getElementById("artifact_types").value,
              pipeline_mode: document.getElementById("pipeline_mode").value,
              product_code: document.getElementById("product_code").value,
              sort_by: document.getElementById("sort_by").value,
              sort_order: document.getElementById("sort_order").value,
              date_from: document.getElementById("date_from").value,
              date_to: document.getElementById("date_to").value,
              page,
              page_size: pageSize,
            };
            const resp = await fetch(`/artifacts?${queryString(params)}`);
            if (!resp.ok) throw new Error(await resp.text());
            const data = await resp.json();
            total = data.total;
            document.getElementById("stats").textContent = `total=${data.total}, page=${data.page}, page_size=${data.page_size}`;
            const grid = document.getElementById("asset-grid");
            grid.innerHTML = "";
            if (!data.items.length) {
              grid.innerHTML = '<div class="empty">No assets match current filters.</div>';
              return;
            }
            data.items.forEach((item) => {
              const el = document.createElement("article");
              el.className = "asset-card";
              const isImage = item.artifact_type.includes("image");
              const isVideo = item.artifact_type.includes("video") || item.uri.endsWith(".mp4");
              const media = isImage
                ? `<a href="${mediaViewUrl(item.uri)}" target="_blank"><img class="media-preview image" src="${mediaUrl(item.uri)}" alt="asset"/></a>`
                : isVideo
                  ? `<a href="${mediaViewUrl(item.uri)}" target="_blank" class="muted">Open video</a><video controls playsinline class="media-preview video" src="${mediaUrl(item.uri)}"></video>`
                  : `<div class="muted">No direct preview.</div>`;
              el.innerHTML = `
                <div><span class="pill">${esc(item.artifact_type)}</span><span class="pill">${esc(item.pipeline_mode)}</span><span class="pill">${esc(item.product_code || "-")}</span></div>
                <div class="muted">run: <a href="/dashboard#run=${esc(item.run_id)}">${esc(item.run_id)}</a></div>
                ${media}
                <div style="margin-top:8px;">${esc(item.preview_text || "-")}</div>
                <div class="muted">score=${esc(item.score ?? "-")} | ${esc(item.created_at)}</div>
                <div class="muted">${esc(item.uri)}</div>
              `;
              grid.appendChild(el);
            });
          }
          function prevPage(){ if (page > 1) { page -= 1; refreshAssets(); } }
          function nextPage(){ if ((page * pageSize) < total) { page += 1; refreshAssets(); } }
          refreshAssets();
        </script>
      </body>
    </html>
    """


@router.get("/", response_class=HTMLResponse)
def dashboard_root() -> str:
    return _dashboard_html()


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page() -> str:
    return _dashboard_html()


@router.get("/dashboard/assets", response_class=HTMLResponse)
def dashboard_assets_page() -> str:
    return _assets_dashboard_html()


@router.get("/dashboard/personas", response_class=HTMLResponse)
def dashboard_personas_page() -> str:
    return _personas_dashboard_html()


@router.get("/dashboard/data-sources", response_model=DataSourceListResponse)
def dashboard_data_sources() -> DataSourceListResponse:
    active_url = get_active_database_url()
    urls = list_local_sqlite_database_urls()
    return DataSourceListResponse(
        active_url=active_url,
        items=[_serialize_data_source(item, active_url=active_url) for item in urls],
    )


@router.post("/dashboard/data-sources/select", response_model=DataSourceListResponse)
def dashboard_select_data_source(payload: DataSourceSelectRequest) -> DataSourceListResponse:
    try:
        active_url = switch_database_url(payload.url)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"failed to switch data source: {exc}") from exc
    urls = list_local_sqlite_database_urls()
    return DataSourceListResponse(
        active_url=active_url,
        items=[_serialize_data_source(item, active_url=active_url) for item in urls],
    )


@router.get("/media")
def media_file(path: str = Query(..., min_length=1)) -> FileResponse:
    requested = _resolve_media_path(path)
    media_type = "application/octet-stream"
    guessed, _ = mimetypes.guess_type(str(requested))
    if guessed:
        media_type = guessed
    return FileResponse(path=str(requested), media_type=media_type)


@router.get("/media/view", response_class=HTMLResponse)
def media_view(path: str = Query(..., min_length=1)) -> str:
    requested = _resolve_media_path(path)
    media_type = mimetypes.guess_type(str(requested))[0] or "application/octet-stream"
    media_src = f"/media?path={quote(str(requested), safe='')}"
    title = requested.name
    if media_type.startswith("image/"):
        body = f'<img class="viewer-media image" src="{media_src}" alt="{title}" />'
    elif media_type.startswith("video/"):
        body = f'<video class="viewer-media video" src="{media_src}" controls playsinline autoplay muted></video>'
    else:
        body = f'<a href="{media_src}">Download {title}</a>'
    return f"""
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>{title}</title>
        <style>
          html, body {{
            margin: 0;
            min-height: 100%;
            background: #0b0f0d;
            color: #eef6f1;
            font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          }}
          .viewer {{
            min-height: 100vh;
            display: grid;
            grid-template-rows: auto 1fr;
          }}
          .bar {{
            padding: 10px 14px;
            border-bottom: 1px solid rgba(255,255,255,0.12);
            font-size: 13px;
            color: #b8c8c0;
            overflow-wrap: anywhere;
          }}
          .stage {{
            min-height: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 14px;
            box-sizing: border-box;
          }}
          .viewer-media {{
            max-width: calc(100vw - 28px);
            max-height: calc(100vh - 62px);
            object-fit: contain;
            background: #050807;
          }}
          .viewer-media.image {{
            width: auto;
            height: auto;
          }}
          .viewer-media.video {{
            width: auto;
            height: auto;
          }}
        </style>
      </head>
      <body>
        <main class="viewer">
          <div class="bar">{title}</div>
          <div class="stage">{body}</div>
        </main>
      </body>
    </html>
    """


@router.get("/dashboard/agent-apis", response_class=HTMLResponse)
def dashboard_agent_apis(db: Session = Depends(get_db)) -> str:
    personas = [PersonaMeta(**row).model_dump(mode="json") for row in list_persona_catalog()]
    configs = [_serialize_agent_config(row).model_dump(mode="json") for row in list_agent_configs(db)]
    db.commit()
    return _agent_api_dashboard_html(
        personas_json=json.dumps(personas, ensure_ascii=False).replace("</", "<\\/"),
        configs_json=json.dumps(configs, ensure_ascii=False).replace("</", "<\\/"),
        env_vars_json=json.dumps(list_api_key_env_names(), ensure_ascii=False).replace("</", "<\\/"),
    )


@router.get("/pipeline-modes", response_model=list[PipelineModeView])
def list_pipeline_modes() -> list[PipelineModeView]:
    return _pipeline_mode_views()


# ── Shop Analysis ─────────────────────────────────────────────────

@router.post("/shop-analysis/run", response_model=ShopAnalysisResponse)
def run_shop_analysis(
    payload: ShopAnalysisRequest,
    db: Session = Depends(get_db),
) -> dict:
    from app.agents.runtime import AgentsRuntime
    from app.services.agent_api_configs import resolve_agent_config, resolve_agent_runtime
    from app.services.shop_analysis import (
        _get_or_create_workspace_project,
        save_shop_profile,
        save_competitor_analysis,
    )

    workspace, project = _get_or_create_workspace_project(
        db, payload.workspace_name, payload.project_name
    )
    runtime = AgentsRuntime()
    config = resolve_agent_config(db, agent_name="shop_analyst", run_provider="", run_model="")
    provider = config["provider_name"]
    model = config["model_name"]
    runtime_config = resolve_agent_runtime(config)

    # Extract search tool API keys from config extra
    extra = config.get("extra") or {}
    tavily_cfg = extra.get("tavily_config") or {}
    firecrawl_cfg = extra.get("firecrawl_config") or {}
    import os
    tavily_api_key = os.getenv(tavily_cfg.get("api_key_env", "")) if tavily_cfg.get("api_key_env") else None
    firecrawl_api_key = os.getenv(firecrawl_cfg.get("api_key_env", "")) if firecrawl_cfg.get("api_key_env") else None

    analysis_id = str(uuid.uuid4())
    errors: list[str] = []

    # Phase 1: Store profile
    profile_result = None
    try:
        result = runtime.run_shop_profile_analysis(
            store_url=payload.store_url,
            description=payload.description,
            provider=provider,
            model=model,
            runtime_config=runtime_config,
            tavily_api_key=tavily_api_key,
            firecrawl_api_key=firecrawl_api_key,
        )
        entry = save_shop_profile(
            db,
            project_id=project.id,
            industry_code=payload.industry_code,
            store_url=payload.store_url,
            profile_data=result["profile"],
        )
        profile_result = {
            "source_type": "shop_profile",
            "content": entry.content,
            "summary": result["profile"].get("positioning", payload.store_url),
        }
    except Exception as exc:
        errors.append(f"shop_profile: {exc}")

    # Phase 2: Competitor analysis (depends on profile success)
    competitor_result = None
    if profile_result:
        try:
            result = runtime.run_competitor_analysis(
                store_url=payload.store_url,
                description=payload.description,
                store_profile=profile_result["content"].get("profile", {}),
                provider=provider,
                model=model,
                runtime_config=runtime_config,
                tavily_api_key=tavily_api_key,
                firecrawl_api_key=firecrawl_api_key,
            )
            entry = save_competitor_analysis(
                db,
                project_id=project.id,
                industry_code=payload.industry_code,
                store_url=payload.store_url,
                analysis_markdown=result["report"],
            )
            competitor_result = {
                "source_type": "competitor_analysis",
                "content": entry.content,
                "summary": result["report"][:120] + "..." if len(result["report"]) > 120 else result["report"],
            }
        except Exception as exc:
            errors.append(f"competitor_analysis: {exc}")

    db.commit()

    status = "failed" if not profile_result and not competitor_result else "completed"
    return ShopAnalysisResponse(
        id=analysis_id,
        store_url=payload.store_url,
        industry_code=payload.industry_code,
        profile=profile_result,
        competitor_analysis=competitor_result,
        status=status,
        error_message="; ".join(errors) if errors else None,
        created_at=datetime.now(UTC),
    ).model_dump(mode="json")


@router.get("/shop-analysis/history", response_model=ShopAnalysisHistoryResponse)
def shop_analysis_history(
    workspace_name: str = Query(default="workspace_demo"),
    project_name: str = Query(default="project_demo"),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    from app.services.shop_analysis import _get_or_create_workspace_project
    _, project = _get_or_create_workspace_project(db, workspace_name, project_name)
    items = list_shop_analyses(db, project.id, limit=limit)
    return {"items": items}


# ── Creative Preset CRUD ──────────────────────────────────────────

@router.get("/creative-presets", response_model=CreativePresetListResponse)
def list_presets(
    workspace_name: str = Query(default="workspace_demo"),
    db: Session = Depends(get_db),
) -> dict:
    system = []
    for key, spec in list_system_presets().items():
        system.append({"key": key, **spec})
    user = list_user_presets(db, workspace_name)
    return {"system": system, "user": [CreativePresetView.model_validate(p) for p in user]}


@router.post("/creative-presets", response_model=CreativePresetView, status_code=201)
def create_preset(payload: CreativePresetCreate, db: Session = Depends(get_db)) -> CreativePresetView:
    try:
        preset = create_creative_preset(
            db,
            workspace_name=payload.workspace_name,
            name=payload.name,
            image_size=payload.image_size,
            video_size=payload.video_size,
            resolution=payload.resolution,
            video_duration_seconds=payload.video_duration_seconds,
            platform_targets=payload.platform_targets,
        )
        db.commit()
        db.refresh(preset)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return CreativePresetView.model_validate(preset)


@router.put("/creative-presets/{preset_id}", response_model=CreativePresetView)
def update_preset(preset_id: str, payload: CreativePresetUpdate, db: Session = Depends(get_db)) -> CreativePresetView:
    try:
        preset = update_creative_preset(
            db,
            preset_id,
            name=payload.name,
            image_size=payload.image_size,
            video_size=payload.video_size,
            resolution=payload.resolution,
            video_duration_seconds=payload.video_duration_seconds,
            platform_targets=payload.platform_targets,
        )
        db.commit()
        db.refresh(preset)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CreativePresetView.model_validate(preset)


@router.delete("/creative-presets/{preset_id}", status_code=204)
def delete_preset(preset_id: str, db: Session = Depends(get_db)):
    try:
        delete_creative_preset(db, preset_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ── Run Template CRUD ────────────────────────────────────────────

@router.get("/run-templates", response_model=list[RunTemplateView])
def list_templates(
    workspace_name: str = Query(default="workspace_demo"),
    db: Session = Depends(get_db),
) -> list[RunTemplateView]:
    templates = list_run_templates(db, workspace_name)
    return [RunTemplateView.model_validate(t) for t in templates]


@router.post("/run-templates", response_model=RunTemplateView, status_code=201)
def create_template(payload: RunTemplateCreate, db: Session = Depends(get_db)) -> RunTemplateView:
    try:
        template = create_run_template(
            db,
            workspace_name=payload.workspace_name,
            name=payload.name,
            config_json=payload.config_json,
            is_shared=payload.is_shared,
        )
        db.commit()
        db.refresh(template)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RunTemplateView.model_validate(template)


@router.put("/run-templates/{template_id}", response_model=RunTemplateView)
def update_template(template_id: str, payload: RunTemplateUpdate, db: Session = Depends(get_db)) -> RunTemplateView:
    try:
        template = update_run_template(
            db,
            template_id,
            name=payload.name,
            config_json=payload.config_json,
            is_shared=payload.is_shared,
        )
        db.commit()
        db.refresh(template)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RunTemplateView.model_validate(template)


@router.delete("/run-templates/{template_id}", status_code=204)
def delete_template(template_id: str, db: Session = Depends(get_db)):
    try:
        delete_run_template(db, template_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ── Product Config Hint ──────────────────────────────────────────

@router.get("/product-config-hint", response_model=ProductConfigHint | None)
def product_config_hint(
    product_code: str = Query(...),
    db: Session = Depends(get_db),
) -> dict | None:
    return get_last_product_config(db, product_code)


@router.post("/runs/preflight", response_model=RunPreflightResponse)
def preflight_pipeline_run(payload: RunPreflightRequest, db: Session = Depends(get_db)) -> RunPreflightResponse:
    result = preflight_run_capabilities(
        db,
        pipeline_mode=payload.pipeline_mode,
        has_image_inputs=payload.has_image_inputs,
        has_video_inputs=payload.has_video_inputs,
    )
    return RunPreflightResponse(**result)


@router.get("/runs", response_model=list[RunSummary])
def list_runs(db: Session = Depends(get_db)) -> list[RunSummary]:
    runs = db.scalars(select(PipelineRun).order_by(desc(PipelineRun.created_at)).limit(50)).all()
    return [
        RunSummary(
            id=run.id,
            status=run.status,
            current_stage=run.current_stage,
            pipeline_mode=run.pipeline_mode,
            project_id=run.project_id,
            product_code=run.product_code or "",
            industry_code=run.industry_code or "",
            updated_at=run.updated_at,
        )
        for run in runs
    ]


@router.get("/gm-memory", response_model=list[GmMemoryItem])
def list_gm_memory(
    scope: str | None = Query(default=None),
    product_code: str | None = Query(default=None),
    industry_code: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[GmMemoryItem]:
    query = select(GmMemory).order_by(desc(GmMemory.created_at))
    if scope:
        query = query.where(GmMemory.memory_scope == scope)
    if product_code:
        query = query.where(GmMemory.product_code == product_code)
    if industry_code:
        query = query.where(GmMemory.industry_code == industry_code)
    rows = db.scalars(query.limit(limit)).all()
    return [
        GmMemoryItem(
            id=row.id,
            project_id=row.project_id,
            run_id=row.run_id,
            memory_scope=row.memory_scope,
            product_code=row.product_code,
            industry_code=row.industry_code,
            source_type=row.source_type,
            score_hint=row.score_hint,
            content=row.content or {},
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post("/runs", response_model=RunView)
def create_pipeline_run(payload: RunCreateRequest, db: Session = Depends(get_db)) -> RunView:
    try:
        run = create_run(db, payload)
        db.commit()
        db.refresh(run)
    except ValueError as exc:
        db.rollback()
        detail = str(exc)
        status_code = 409 if "conflict" in detail else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return _serialize_run(db, run)


@router.post("/runs/rich")
async def create_pipeline_run_rich(
    workspace_name: str = Form(...),
    project_name: str = Form(...),
    product_name: str = Form(...),
    product_code: str = Form(...),
    industry_code: str = Form(...),
    campaign_name: str = Form(...),
    channel: str = Form("meta"),
    objective: str = Form("conversions"),
    market: str = Form("US"),
    locale: str = Form("en-US"),
    variant_count: int = Form(8),
    creative_preset: str = Form(...),
    creative_specs: str = Form("{}"),
    model_provider: str | None = Form(None),
    model_name: str | None = Form(None),
    pipeline_mode: str = Form(PipelineMode.FULL_MULTIMODAL.value),
    approval_mode: str = Form("manual"),
    enable_research: bool = Form(False),
    manual_research_brief: str = Form(""),
    business_context: str = Form("{}"),
    category_tags: str = Form("[]"),
    url_references: str = Form("[]"),
    files: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    if pipeline_mode not in PIPELINE_STAGE_PLANS:
        raise HTTPException(status_code=400, detail=f"unsupported pipeline_mode: {pipeline_mode}")
    payload = RunCreateRequest(
        workspace_name=workspace_name,
        project_name=project_name,
        product_name=product_name,
        product_code=product_code,
        industry_code=industry_code,
        campaign_name=campaign_name,
        channel=channel,
        objective=objective,
        market=market,
        locale=locale,
        creative_preset=creative_preset,
        creative_specs=_load_json_dict(creative_specs, "creative_specs"),
        variant_count=variant_count,
        model_provider=model_provider,
        model_name=model_name,
        pipeline_mode=pipeline_mode,
        approval_mode=approval_mode,
        enable_research=enable_research,
        manual_research_brief=manual_research_brief,
        business_context=_load_json_dict(business_context, "business_context"),
        category_tags=_load_json_list(category_tags, "category_tags"),
        context={"url_references": _load_json_list(url_references, "url_references")},
    )
    # -- inline preflight --
    has_image = any(
        (f.content_type or "").startswith("image/") for f in files
    )
    has_video = any(
        (f.content_type or "").startswith("video/") for f in files
    )
    preflight_result = preflight_run_capabilities(
        db,
        pipeline_mode=pipeline_mode,
        has_image_inputs=has_image,
        has_video_inputs=has_video,
    )
    # -- end inline preflight --

    try:
        run = create_run(db, payload)
    except ValueError as exc:
        db.rollback()
        detail = str(exc)
        status_code = 409 if "conflict" in detail else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    uploaded_payloads = []
    for file in files:
        content = await file.read()
        uploaded_payloads.append({"filename": file.filename or "upload.bin", "content_type": file.content_type, "content": content})
    try:
        assets_summary, artifacts = process_uploaded_payloads(run.id, uploaded_payloads)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if is_marketplace_main_image(run.creative_specs) and not (
        assets_summary.get("sample_images") or assets_summary.get("sample_videos")
    ):
        db.rollback()
        raise HTTPException(status_code=400, detail="marketplace_main_image requires at least one uploaded product image or video")

    run.context_json = {
        **(run.context_json or {}),
        "input_assets": assets_summary,
        "url_references": payload.context.get("url_references", []),
    }
    for artifact in artifacts:
        db.add(
            Artifact(
                run_id=run.id,
                stage_name="intake",
                artifact_type=artifact["type"],
                uri=artifact["uri"],
                payload=artifact["payload"],
            )
        )
    db.commit()
    db.refresh(run)
    result = _serialize_run(db, run).model_dump()
    result["_preflight"] = preflight_result
    return result


@router.get("/runs/{run_id}", response_model=RunView)
def get_pipeline_run(run_id: str, db: Session = Depends(get_db)) -> RunView:
    try:
        run = get_run(db, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _serialize_run(db, run)


@router.get("/runs/{run_id}/events")
async def stream_run_events(
    run_id: str,
    request: Request,
    since_id: str | None = Query(default=None),
    once: bool = Query(default=False),
    poll_seconds: float = Query(default=1.0, ge=0.2, le=10.0),
) -> StreamingResponse:
    async def event_generator():
        seen: set[str] = set()
        if since_id:
            seen.add(since_id)
        with SessionLocal() as db:
            try:
                get_run(db, run_id)
            except ValueError:
                yield _sse_event("error", {"detail": f"run not found: {run_id}"})
                return
        while True:
            if await request.is_disconnected():
                break
            emitted = False
            with SessionLocal() as db:
                for event in run_trace_events(db, run_id, limit=200):
                    if event.id in seen:
                        continue
                    seen.add(event.id)
                    emitted = True
                    yield _sse_event("agent_trace", _serialize_trace_event(event), event.id)
            if once:
                break
            if not emitted:
                yield _sse_event("heartbeat", {"run_id": run_id})
            await asyncio.sleep(poll_seconds)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/runs/{run_id}/deliverables", response_model=DeliverablesResponse)
def get_run_deliverables(run_id: str, db: Session = Depends(get_db)) -> DeliverablesResponse:
    try:
        run = get_run(db, run_id)
        deliverables = run_deliverables(db, run_id)
        evaluation = get_stage_payload(db, run_id, "evaluation_selection")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    score = (evaluation.get("evaluation_result", {}) if evaluation else {}) or {}
    return DeliverablesResponse(
        run_id=run.id,
        winner_variant_id=deliverables.get("winner_variant_id"),
        deliverables=deliverables,
        score=score,
    )


@router.get("/runs/{run_id}/deliverables.zip")
def get_run_deliverables_zip(run_id: str, db: Session = Depends(get_db)) -> StreamingResponse:
    try:
        run = get_run(db, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    assets = db.scalars(
        select(VariantAsset).where(VariantAsset.run_id == run_id, VariantAsset.asset_type == "image")
    ).all()
    intake_payload = get_stage_payload(db, run_id, "intake") if run.stage_tasks else {}
    exported: list[dict] = []
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for asset in assets:
            payload = asset.payload or {}
            marketplace_qa = payload.get("marketplace_qa") or {}
            readiness = payload.get("platform_readiness") or marketplace_qa.get("platform_readiness") or {}
            variant = db.get(RunVariant, asset.run_variant_id)
            approved = bool(
                variant
                and (
                    variant.is_winner
                    or variant.review_status in {"approved", "winner", "export_ready"}
                    or variant.status in {"approved", "winner"}
                )
            )
            export_ready = bool(payload.get("export_ready") or marketplace_qa.get("export_ready"))
            if not (export_ready or approved):
                continue
            if marketplace_qa.get("status") == "fail" and not approved:
                continue
            try:
                media_path = _resolve_media_path(asset.uri or "")
            except HTTPException:
                continue
            image_role = str(payload.get("image_role") or "main_image").replace("/", "_")
            variant_id = str(payload.get("variant_id") or (variant.variant_id if variant else asset.id)).replace("/", "_")
            suffix = media_path.suffix or ".png"
            export_name = f"{run.product_code}_{variant_id}_{image_role}{suffix}"
            zf.write(media_path, export_name)
            exported.append(
                {
                    "file": export_name,
                    "variant_id": variant_id,
                    "image_role": image_role,
                    "uri": asset.uri,
                    "platform_readiness": readiness,
                    "marketplace_qa": marketplace_qa,
                    "approved": approved,
                    "export_ready": export_ready,
                }
            )
        qa_report = {
            "run_id": run.id,
            "product_code": run.product_code,
            "industry_code": run.industry_code,
            "creative_preset": run.creative_preset,
            "creative_specs": run.creative_specs or {},
            "visual_identity": intake_payload.get("visual_identity") if isinstance(intake_payload, dict) else {},
            "exported_count": len(exported),
            "images": exported,
        }
        zf.writestr("qa_report.json", json.dumps(qa_report, ensure_ascii=False, indent=2))
    archive.seek(0)
    filename = f"{run.product_code or run.id}_deliverables.zip"
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/runs/{run_id}/variants", response_model=VariantsResponse)
def get_run_variants(
    run_id: str,
    status: str | None = Query(default=None),
    review_status: str | None = Query(default=None),
    quality: str | None = Query(default=None),
    asset_type: str | None = Query(default=None),
    generation_status: str | None = Query(default=None),
    compliance: str | None = Query(default=None),
    min_score: float | None = Query(default=None),
    q: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> VariantsResponse:
    try:
        get_run(db, run_id)
        data = run_variants(
            db,
            run_id,
            status=status,
            review_status=review_status,
            quality=quality,
            asset_type=asset_type,
            generation_status=generation_status,
            compliance=compliance,
            min_score=min_score,
            q=q,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return VariantsResponse(
        run_id=run_id,
        variants=data.get("variants", []),
        ranked=data.get("ranked", []),
        items=[RunVariantView(**item) for item in data.get("items", [])],
        summary=data.get("summary", {}),
    )


@router.post("/runs/{run_id}/videos/refresh")
def post_run_video_refresh(run_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        result = refresh_video_task_assets(db, run_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result


@router.post("/runs/{run_id}/assets/refresh")
def post_run_assets_refresh(run_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        result = refresh_async_assets(db, run_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result


@router.post("/runs/{run_id}/variants/{variant_id}/review", response_model=RunVariantView)
def post_variant_review(
    run_id: str,
    variant_id: str,
    payload: VariantReviewRequest,
    db: Session = Depends(get_db),
) -> RunVariantView:
    try:
        variant = review_variant(
            db,
            run_id=run_id,
            variant_id=variant_id,
            action=payload.action,
            comment=payload.comment,
            tags=payload.tags,
        )
        db.commit()
        data = next(item for item in run_variants(db, run_id)["items"] if item["variant_id"] == variant.variant_id)
    except (ValueError, StopIteration) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RunVariantView(**data)


@router.post("/runs/{run_id}/variants/{variant_id}/select", response_model=RunVariantView)
def post_variant_select(
    run_id: str,
    variant_id: str,
    payload: VariantSelectRequest,
    db: Session = Depends(get_db),
) -> RunVariantView:
    try:
        if payload.winner:
            review_variant(
                db,
                run_id=run_id,
                variant_id=variant_id,
                action="set_winner",
                comment=payload.comment,
            )
        elif payload.shortlist:
            review_variant(
                db,
                run_id=run_id,
                variant_id=variant_id,
                action="shortlist_variant",
                comment=payload.comment,
            )
        else:
            raise ValueError("select requires shortlist or winner")
        db.commit()
        data = next(item for item in run_variants(db, run_id)["items"] if item["variant_id"] == variant_id)
    except (ValueError, StopIteration) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RunVariantView(**data)


@router.post("/runs/{run_id}/variants/{variant_id}/regenerate", response_model=RunVariantView)
def post_variant_regenerate(
    run_id: str,
    variant_id: str,
    payload: VariantRegenerateRequest,
    db: Session = Depends(get_db),
) -> RunVariantView:
    try:
        variant = regenerate_variant_assets(
            db,
            run_id=run_id,
            variant_id=variant_id,
            reason=payload.reason,
            target_stage=payload.target_stage,
        )
        db.commit()
        data = next(item for item in run_variants(db, run_id)["items"] if item["variant_id"] == variant_id)
    except (ValueError, StopIteration) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RunVariantView(**data)


@router.get("/artifacts", response_model=ArtifactListResponse)
def list_artifacts(
    q: str | None = Query(default=None),
    artifact_types: str | None = Query(default=None),
    pipeline_mode: str | None = Query(default=None),
    product_code: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    sort_by: str = Query(default="created_at"),
    sort_order: str = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> ArtifactListResponse:
    types = [item.strip() for item in (artifact_types or "").split(",") if item.strip()]
    if not types:
        types = sorted(DEFAULT_GENERATED_ARTIFACT_TYPES)
    if sort_by not in {"created_at", "score"}:
        raise HTTPException(status_code=400, detail="sort_by must be created_at or score")
    if sort_order not in {"asc", "desc"}:
        raise HTTPException(status_code=400, detail="sort_order must be asc or desc")
    try:
        start_dt = _parse_date_start(date_from)
        end_dt = _parse_date_end(date_to)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid date: {exc}") from exc

    score_expr = (
        select(func.max(ScoreCardModel.total_score))
        .where(ScoreCardModel.run_id == Artifact.run_id)
        .scalar_subquery()
    )
    query = (
        select(
            Artifact.id,
            Artifact.run_id,
            Artifact.artifact_type,
            Artifact.stage_name,
            Artifact.uri,
            Artifact.payload,
            Artifact.created_at,
            PipelineRun.pipeline_mode,
            PipelineRun.product_code,
            score_expr.label("score"),
        )
        .join(PipelineRun, PipelineRun.id == Artifact.run_id)
        .where(Artifact.artifact_type.in_(types))
    )

    if q:
        pattern = f"%{q.lower()}%"
        query = query.where(
            or_(
                func.lower(Artifact.run_id).like(pattern),
                func.lower(Artifact.uri).like(pattern),
                func.lower(cast(Artifact.payload, String)).like(pattern),
            )
        )
    if pipeline_mode:
        query = query.where(PipelineRun.pipeline_mode == pipeline_mode)
    if product_code:
        query = query.where(PipelineRun.product_code == product_code)
    if start_dt:
        query = query.where(Artifact.created_at >= start_dt)
    if end_dt:
        query = query.where(Artifact.created_at < end_dt)

    count_stmt = select(func.count()).select_from(query.subquery())
    total = int(db.scalar(count_stmt) or 0)

    if sort_by == "score":
        if sort_order == "asc":
            query = query.order_by(func.coalesce(score_expr, 101.0).asc(), desc(Artifact.created_at))
        else:
            query = query.order_by(desc(func.coalesce(score_expr, -1.0)), desc(Artifact.created_at))
    elif sort_order == "asc":
        query = query.order_by(Artifact.created_at.asc())
    else:
        query = query.order_by(desc(Artifact.created_at))

    rows = db.execute(query.offset((page - 1) * page_size).limit(page_size)).all()
    items = [
        ArtifactListItem(
            artifact_id=row.id,
            run_id=row.run_id,
            artifact_type=row.artifact_type,
            stage_name=row.stage_name,
            pipeline_mode=row.pipeline_mode,
            product_code=row.product_code or "",
            uri=row.uri,
            preview_text=_artifact_preview(row.payload or {}),
            score=float(row.score) if row.score is not None else None,
            created_at=row.created_at,
        )
        for row in rows
    ]
    return ArtifactListResponse(page=page, page_size=page_size, total=total, items=items)


def get_stage_payload(db: Session, run_id: str, stage_name: str) -> dict:
    task = db.scalar(select(StageTask).where(StageTask.run_id == run_id, StageTask.stage_name == stage_name))
    if not task:
        raise ValueError(f"stage task not found: {run_id}/{stage_name}")
    return task.output_payload or {}


@router.post("/runs/{run_id}/advance", response_model=RunView)
def advance_pipeline_run(run_id: str, payload: ReviewActionRequest, db: Session = Depends(get_db)) -> RunView:
    try:
        run = approve_stage(db, run_id, notes=payload.notes)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _serialize_run(db, run)


@router.post("/runs/{run_id}/reject", response_model=RunView)
def reject_pipeline_run(run_id: str, payload: ReviewActionRequest, db: Session = Depends(get_db)) -> RunView:
    try:
        run = reject_stage(db, run_id, notes=payload.notes)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _serialize_run(db, run)


@router.post("/feedback/import", response_model=FeedbackImportResponse)
def import_feedback(payload: FeedbackImportRequest, db: Session = Depends(get_db)) -> FeedbackImportResponse:
    import_record, snapshots, memory = import_feedback_rows(
        db=db,
        workspace_name=payload.workspace_name,
        project_name=payload.project_name,
        rows=payload.rows,
        file_name=payload.file_name,
    )
    db.commit()
    return FeedbackImportResponse(
        import_id=import_record.id,
        rows=import_record.row_count,
        snapshots_created=snapshots,
        memory_entry_id=memory.id if memory else None,
    )


@router.get("/projects/{project_id}/leaderboard", response_model=LeaderboardResponse)
def leaderboard(project_id: str, db: Session = Depends(get_db)) -> LeaderboardResponse:
    ranking = [LeaderboardItem(**item) for item in project_leaderboard(db, project_id)]
    return LeaderboardResponse(project_id=project_id, ranking=ranking)


@router.get("/personas", response_model=list[PersonaMeta])
def list_agent_personas() -> list[PersonaMeta]:
    return [PersonaMeta(**row) for row in list_persona_catalog()]


@router.get("/personas/{agent_name}", response_model=PersonaView)
def read_agent_persona(agent_name: str, db: Session = Depends(get_db)) -> PersonaView:
    try:
        content, version, source_path = get_persona(db, agent_name)
    except (FileNotFoundError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    info = persona_info(agent_name)
    return PersonaView(
        agent_name=agent_name,
        display_name=info["display_name"],
        stage=info["stage"],
        role=info["role"],
        content=content,
        version=version,
        source_path=source_path,
    )


@router.patch("/personas/{agent_name}", response_model=PersonaView)
def patch_agent_persona(agent_name: str, payload: PersonaPatchRequest, db: Session = Depends(get_db)) -> PersonaView:
    try:
        content, version, source_path = update_persona(db, agent_name, payload.content, payload.changed_by)
        info = persona_info(agent_name)
    except KeyError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return PersonaView(
        agent_name=agent_name,
        display_name=info["display_name"],
        stage=info["stage"],
        role=info["role"],
        content=content,
        version=version,
        source_path=source_path,
    )


@router.get("/agent-configs", response_model=list[AgentApiConfigView])
def get_agent_configs(db: Session = Depends(get_db)) -> list[AgentApiConfigView]:
    rows = list_agent_configs(db)
    db.commit()
    return [_serialize_agent_config(row) for row in rows]


@router.get("/agent-configs/env-vars", response_model=list[str])
def get_agent_config_env_vars() -> list[str]:
    return list_api_key_env_names()


@router.patch("/agent-configs/{agent_name}", response_model=AgentApiConfigView)
def patch_agent_config(agent_name: str, payload: AgentApiConfigPatchRequest, db: Session = Depends(get_db)) -> AgentApiConfigView:
    try:
        row = upsert_agent_config(
            db,
            agent_name=agent_name,
            provider_name=payload.provider_name,
            model_name=payload.model_name,
            api_base_url=payload.api_base_url,
            api_key_env=payload.api_key_env,
            image_provider_name=payload.image_provider_name,
            image_model_name=payload.image_model_name,
            image_api_base_url=payload.image_api_base_url,
            image_api_key_env=payload.image_api_key_env,
            video_provider_name=payload.video_provider_name,
            video_model_name=payload.video_model_name,
            video_api_base_url=payload.video_api_base_url,
            video_api_key_env=payload.video_api_key_env,
            thinking_mode=payload.thinking_mode,
            thinking_budget_tokens=payload.thinking_budget_tokens,
            max_output_tokens=payload.max_output_tokens,
            request_timeout_seconds=payload.request_timeout_seconds,
            streaming_enabled=payload.streaming_enabled,
            extra=payload.extra,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return _serialize_agent_config(row)

from __future__ import annotations

import json
import mimetypes
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import String, cast, desc, func, or_, select
from sqlalchemy.orm import Session

from app.agents.registry import stage_agent
from app.core.config import get_settings
from app.data.models import Artifact, GmMemory, PipelineRun, ScoreCard as ScoreCardModel, StageTask
from app.data.session import (
    get_active_database_url,
    get_db,
    list_local_sqlite_database_urls,
    switch_database_url,
)
from app.orchestrator.state_machine import PIPELINE_STAGE_PLANS, PipelineMode
from app.schemas.api import (
    AgentApiConfigPatchRequest,
    AgentApiConfigView,
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
    ReviewActionRequest,
    RunCreateRequest,
    RunSummary,
    RunView,
    StageTaskView,
    VariantsResponse,
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
from app.services.personas import get_persona, list_persona_catalog, persona_info, update_persona
from app.services.creative_specs import list_creative_presets
from app.services.runs import (
    approve_stage,
    create_run,
    get_run,
    latest_scorecard,
    reject_stage,
    run_deliverables,
    run_variants,
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
        enable_research=run.enable_research,
        manual_research_brief=run.manual_research_brief or "",
        business_context=run.business_context or {},
        category_tags=run.category_tags or [],
        budget_used=run.budget_used,
        variant_count=run.variant_count,
        created_at=run.created_at,
        updated_at=run.updated_at,
        stage_tasks=task_views,
        latest_scorecard=scorecard,
        latest_forecast=forecast,
    )


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
        extra=row.extra or {},
        is_default=row.agent_name == "default",
        updated_at=row.updated_at,
    )


def _dashboard_html() -> str:
    return """
    <html>
      <head>
        <title>Crispy Dashboard</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>
          :root {
            --bg: #f4f7f2;
            --bg-alt: #e9f1f7;
            --card: rgba(255, 255, 255, 0.9);
            --text: #173027;
            --muted: #5d6f66;
            --line: #d9e4dc;
            --accent: #1f7a62;
            --accent-dark: #145746;
            --soft: #edf5f0;
            --danger: #be3b3b;
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
          .app-shell { width: min(1460px, calc(100% - 24px)); margin: 22px auto 36px auto; }
          .hero {
            display: flex;
            justify-content: space-between;
            align-items: flex-end;
            gap: 12px;
            margin-bottom: 14px;
          }
          h1, h2, h3 { margin: 0; line-height: 1.25; }
          h1 { font-size: 28px; letter-spacing: -0.02em; }
          h2 { font-size: 20px; margin-bottom: 10px; }
          h3 { font-size: 15px; margin-bottom: 8px; }
          .subtitle { color: var(--muted); margin-top: 6px; font-size: 14px; }
          .topbar { display:flex; justify-content:space-between; align-items:end; gap:12px; margin-bottom:14px; }
          .links { display:flex; gap:10px; flex-wrap: wrap; }
          a { color: var(--accent-dark); text-decoration: none; }
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
            padding: 16px;
            background: var(--card);
            box-shadow: 0 8px 24px rgba(30, 62, 50, 0.07);
            backdrop-filter: blur(4px);
          }
          .grid { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr); gap: 16px; align-items: start; }
          .row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
          .table-wrap { overflow: auto; border-radius: 12px; border: 1px solid var(--line); }
          table { width: 100%; border-collapse: collapse; font-size: 13px; min-width: 620px; }
          th, td { border-bottom: 1px solid #e8eee8; padding: 9px 10px; text-align: left; vertical-align: top; }
          thead th { background: #f8fbf8; font-weight: 700; color: #295345; }
          tr.selected { background: #eef8f2; }
          tr:hover { background: #f8fcfa; }
          textarea, input, select {
            width: 100%;
            padding: 9px 10px;
            border-radius: 10px;
            border: 1px solid #c8d8ce;
            margin: 4px 0 10px 0;
            background: #fff;
            color: var(--text);
            font-size: 14px;
          }
          textarea:focus, input:focus, select:focus {
            outline: none;
            border-color: var(--accent);
            box-shadow: 0 0 0 3px rgba(31, 122, 98, 0.16);
          }
          button {
            padding: 8px 12px;
            border-radius: 10px;
            border: 1px solid #c0d0c6;
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
          button.primary:hover { filter: brightness(0.96); }
          .action-row { margin-bottom: 10px; display:flex; gap:8px; flex-wrap: wrap; }
          .hint {
            padding: 8px 10px;
            border: 1px solid #d8e8df;
            border-radius: 10px;
            background: var(--soft);
            margin-bottom: 8px;
          }
          .muted { color: var(--muted); font-size: 12px; }
          .mono { font-family: var(--mono); }
          .pill {
            display:inline-block;
            padding:2px 8px;
            border-radius:20px;
            font-size:12px;
            border:1px solid #c9ddd1;
            background: #f7fcf8;
            margin-right:6px;
            margin-bottom:4px;
          }
          .deliverables { display:grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap:10px; margin-top:10px; }
          .deliverable-card {
            border:1px solid #deebe2;
            border-radius:12px;
            padding:11px;
            background:#fdfefe;
            min-height: 190px;
          }
          .stage-title { font-weight: 700; margin-bottom: 4px; color: #1f463a; }
          .timeline {
            margin-top: 12px;
            max-height: 560px;
            overflow-y: auto;
            border:1px solid #dfeadf;
            border-radius:12px;
            padding:10px;
            background:#fcfffd;
          }
          .stage-card {
            border-left: 3px solid #8dbda8;
            padding: 8px 10px;
            margin-bottom: 10px;
            background:#f7fcf8;
            border-radius: 8px;
          }
          .img-preview {
            width: 100%;
            border-radius: 10px;
            border: 1px solid #dce7e1;
            object-fit: cover;
            max-height: 220px;
            background:#f2f5fa;
          }
          pre {
            white-space: pre-wrap;
            word-break: break-word;
            border: 1px solid #d8e4db;
            border-radius: 10px;
            padding: 10px;
            background: #f7faf8;
            font-size: 12px;
          }
          summary { cursor: pointer; font-weight: 600; color: #2a5b4a; }
          .persona-chips { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
          .persona-chip { border-radius: 999px; padding: 6px 10px; font-size: 12px; }
          .persona-chip-gm { border-color: #8cbda6; background: #eaf7f1; color: #154a3b; font-weight: 700; }
          .persona-divider { border-top: 1px dashed #c7dbce; margin: 2px 0 10px 0; }
          .status-msg { margin-top: 6px; font-size: 13px; font-weight: 600; }
          .status-ok { color: #1f7a62; }
          .status-error { color: var(--danger); }
          .run-detail-empty { padding: 12px; background: #f5faf6; border-radius: 10px; border: 1px dashed #c8dacd; }
          @media (max-width: 1140px) {
            .grid { grid-template-columns: 1fr; }
            .topbar { align-items: flex-start; flex-direction: column; }
          }
          @media (max-width: 860px) {
            .app-shell { width: calc(100% - 12px); margin-top: 10px; }
            .row { grid-template-columns: 1fr; gap: 0; }
            .deliverables { grid-template-columns: 1fr; }
            .hero { flex-direction: column; align-items: flex-start; }
          }
        </style>
      </head>
      <body>
        <main class="app-shell">
          <header class="hero">
            <div>
              <h1>Crispy Dashboard</h1>
              <div class="subtitle">Production MVP control plane for multimodal creative generation and review.</div>
              <div class="subtitle">Flow: input product/task -> GM intake summary -> planning with product+industry memory -> divergence -> copy/image & video generation -> evaluation winner -> feedback updates GM memory.</div>
            </div>
          </header>
          <div class="topbar">
            <div class="links">
              <a class="nav-link" href="/dashboard/agent-apis">Agent API Configs</a>
              <a class="nav-link" href="/dashboard/assets">Asset Library</a>
            </div>
            <div style="min-width: min(520px, 100%);">
              <label>Data Source</label>
              <select id="data-source-select" onchange="switchDataSource()"></select>
              <div id="data-source-path" class="muted mono"></div>
            </div>
          </div>
          <div class="grid">
            <section class="card">
              <h2>Runs</h2>
              <div class="action-row">
                <button onclick="refreshRuns()">Refresh</button>
                <button onclick="advanceRun()">Advance</button>
                <button onclick="rejectRun()">Reject</button>
              </div>
              <div class="table-wrap">
                <table>
                  <thead><tr><th>Run ID</th><th>Status</th><th>Stage</th><th>Mode</th><th>Updated</th></tr></thead>
                  <tbody id="runs-body"></tbody>
                </table>
              </div>
            </section>
            <section class="card">
              <h2>Create Run</h2>
              <form onsubmit="createRun(event)">
                <div class="row">
                  <div><label>Workspace</label><input id="workspace_name" value="workspace_demo" /></div>
                  <div><label>Project</label><input id="project_name" value="project_demo" /></div>
                </div>
                <div class="row">
                  <div><label>Product</label><input id="product_name" value="dog leash" /></div>
                  <div><label>Campaign</label><input id="campaign_name" value="meta_dog_leash_1" /></div>
                </div>
                <div class="row">
                  <div><label>Product Code (required)</label><input id="product_code" value="DL-001" required /></div>
                  <div><label>Industry Code (required)</label><input id="industry_code" value="pet_accessories" required /></div>
                </div>
                <div class="row">
                  <div><label>Pipeline Mode</label><select id="pipeline_mode"></select></div>
                  <div><label>Variant Count</label><input id="variant_count" type="number" min="1" max="16" value="8" /></div>
                </div>
                <div id="mode-summary" class="hint muted">Loading pipeline modes...</div>
                <div class="row">
                  <div>
                    <label>Creative Preset (required)</label>
                    <select id="creative_preset" onchange="refreshPresetHint()">
                      <option value="meta_square_5s" selected>Meta Square 5s</option>
                      <option value="meta_vertical_5s">Meta Vertical 5s</option>
                      <option value="youtube_landscape_6s">YouTube Landscape 6s</option>
                      <option value="custom">Custom</option>
                    </select>
                  </div>
                  <div><label>Channel</label><input id="channel" value="meta" /></div>
                </div>
                <div id="preset-hint" class="hint muted"></div>
                <div class="row">
                  <div><label>Image Size (custom only)</label><input id="custom_image_size" placeholder="1:1" /></div>
                  <div><label>Video Size (custom only)</label><input id="custom_video_size" placeholder="9:16" /></div>
                </div>
                <div class="row">
                  <div><label>Resolution (custom only)</label><input id="custom_resolution" placeholder="720p" /></div>
                  <div><label>Video Duration Seconds (custom only)</label><input id="custom_duration" type="number" min="1" max="60" placeholder="5" /></div>
                </div>
                <div class="row">
                  <div><label>Objective</label><input id="objective" value="conversions" /></div>
                  <div></div>
                </div>
                <label>Product Description</label>
                <textarea id="product_description" rows="3" placeholder="What is the product, who uses it, and why it matters."></textarea>
                <div class="row">
                  <div><label>Target Audience</label><input id="target_audience" value="dog owners in US cities" /></div>
                  <div><label>Price Range</label><input id="price_range" placeholder="$19.99 - $29.99" /></div>
                </div>
                <label>Key Value Props (comma separated)</label>
                <input id="key_value_props" value="hands-free walking,anti-pull comfort,durable nylon" />
                <div class="row">
                  <div><label>Primary CTA</label><input id="primary_cta" value="Shop Now" /></div>
                  <div><label>Campaign Goal</label><input id="campaign_goal" value="purchase" /></div>
                </div>
                <label>Category Tags (comma separated)</label>
                <input id="category_tags" value="pet_accessories,dog" />
                <label>Reference URLs (one per line)</label>
                <textarea id="url_references" rows="2" placeholder="https://example.com/product"></textarea>
                <label>Research Source</label>
                <select id="research_mode" onchange="refreshResearchHint()">
                  <option value="manual_validated" selected>Use my validated research (Default)</option>
                  <option value="autonomous_web">Run autonomous web research</option>
                </select>
                <div id="research-hint" class="hint muted"></div>
                <label>Validated Research Notes (optional)</label>
                <textarea id="manual_research_brief" rows="3" placeholder="Paste your manually validated market notes, claims boundaries, and competitor findings."></textarea>
                <label>Advanced Business Context JSON (optional)</label>
                <textarea id="business_context_extra" rows="3" placeholder='{"landing_page_angle":"premium utility","seasonality":"spring"}'></textarea>
                <label>Upload Product Inputs (max 10 files, 50MB each, 200MB total)</label>
                <input id="input_files" type="file" multiple accept=".csv,.xlsx,.png,.jpg,.jpeg,.webp,.mp4,.mov,.m4v" />
                <button class="primary" type="submit">Create Run</button>
              </form>
              <div id="create-msg" class="status-msg muted"></div>
            </section>
          </div>
          <div class="grid" style="margin-top:18px;">
            <section class="card">
              <h2>Run Detail</h2>
              <div id="run-detail" class="run-detail-empty">Select a run.</div>
            </section>
            <section class="card">
              <h2>Persona Manager</h2>
              <div id="persona-list"></div>
              <textarea id="persona-content" rows="12" style="display:none"></textarea>
              <button id="persona-save" style="display:none" onclick="savePersona()">Save Persona</button>
              <div id="persona-msg" class="status-msg muted"></div>
            </section>
          </div>
        </main>
        <script>
          let currentRunId = null;
          let currentPersona = null;
          let pipelineModes = [];
          let dataSources = [];
          let dataSourceSelectInFlight = false;

          function esc(v){ return String(v ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;");}
          function toList(raw){ return String(raw || "").split(",").map(s => s.trim()).filter(Boolean); }
          function parseJsonObject(raw){
            if (!raw || !raw.trim()) return {};
            try { return JSON.parse(raw); } catch (_e) { throw new Error("Advanced Business Context JSON is invalid."); }
          }
          function buildCreativeSpecs() {
            const preset = document.getElementById("creative_preset").value;
            if (preset === "meta_square_5s") return { image_size: "1:1", video_size: "1:1", resolution: "720p", video_duration_seconds: 5 };
            if (preset === "meta_vertical_5s") return { image_size: "9:16", video_size: "9:16", resolution: "720p", video_duration_seconds: 5 };
            if (preset === "youtube_landscape_6s") return { image_size: "16:9", video_size: "16:9", resolution: "1080p", video_duration_seconds: 6 };
            const imageSize = document.getElementById("custom_image_size").value.trim();
            const videoSize = document.getElementById("custom_video_size").value.trim();
            const resolution = document.getElementById("custom_resolution").value.trim();
            const durationRaw = document.getElementById("custom_duration").value.trim();
            const duration = Number(durationRaw);
            if (!imageSize || !videoSize || !resolution || !durationRaw || Number.isNaN(duration) || duration <= 0) {
              throw new Error("Custom preset requires image_size, video_size, resolution, and positive video duration.");
            }
            return { image_size: imageSize, video_size: videoSize, resolution, video_duration_seconds: Math.round(duration) };
          }
          function refreshPresetHint() {
            const preset = document.getElementById("creative_preset").value;
            const hint = document.getElementById("preset-hint");
            const isCustom = preset === "custom";
            ["custom_image_size", "custom_video_size", "custom_resolution", "custom_duration"].forEach((id) => {
              const el = document.getElementById(id);
              el.disabled = !isCustom;
            });
            if (preset === "meta_square_5s") hint.textContent = "Preset: image/video 1:1, 720p, duration 5s.";
            else if (preset === "meta_vertical_5s") hint.textContent = "Preset: image/video 9:16, 720p, duration 5s.";
            else if (preset === "youtube_landscape_6s") hint.textContent = "Preset: image/video 16:9, 1080p, duration 6s.";
            else hint.textContent = "Custom preset: fill image/video size, resolution, and duration manually.";
          }
          function mediaUrl(path){ return `/media?path=${encodeURIComponent(path || "")}`; }

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

          async function refreshRuns() {
            const rows = await api("/runs");
            const body = document.getElementById("runs-body");
            body.innerHTML = "";
            if (!rows.length) {
              const tr = document.createElement("tr");
              tr.innerHTML = `<td colspan="5" class="muted">No runs available in current data source.</td>`;
              body.appendChild(tr);
              return;
            }
            rows.forEach((r) => {
              const tr = document.createElement("tr");
              if (r.id === currentRunId) tr.classList.add("selected");
              tr.innerHTML = `<td><a href="#" onclick="selectRun('${r.id}');return false;">${r.id.slice(0,8)}</a></td><td>${esc(r.status)}</td><td>${esc(r.current_stage||"-")}</td><td>${esc(r.pipeline_mode)}</td><td>${esc(r.updated_at)}</td>`;
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
                    <a href="${mediaUrl(image.uri)}" target="_blank">
                      <img class="img-preview" src="${mediaUrl(image.uri)}" alt="generated image" />
                    </a>
                    <div class="muted">${esc(image.aspect_ratio || "1:1")} | ${esc(image.uri)}</div>
                  ` : '<div class="muted">No image winner yet.</div>'}
                </article>
                <article class="deliverable-card">
                  <div class="stage-title">Video</div>
                  ${video ? `
                    <video controls class="img-preview" src="${mediaUrl(video.video_uri)}"></video>
                    <div class="muted">${esc(video.video_uri)}</div>
                  ` : '<div class="muted">No video winner yet.</div>'}
                </article>
              </div>
            `;
          }

          function renderTimeline(run) {
            const stageHtml = (run.stage_tasks || []).map((task) => {
              const agent = task.metadata_json?.agent_name || "-";
              return `
                <article class="stage-card">
                  <div class="stage-title">${esc(task.stage_name)}</div>
                  <div>
                    <span class="pill">status: ${esc(task.status)}</span>
                    <span class="pill">attempt: ${esc(task.attempt)}</span>
                    <span class="pill">agent: ${esc(agent)}</span>
                  </div>
                  <div>${esc(task.summary || "No summary")}</div>
                  <div class="muted">started: ${esc(task.started_at || "-")} | completed: ${esc(task.completed_at || "-")} | review: ${esc(task.review_notes || "-")}</div>
                  <details>
                    <summary>Raw JSON</summary>
                    <pre>${esc(JSON.stringify(task.output_payload || {}, null, 2))}</pre>
                  </details>
                </article>
              `;
            }).join("");
            return stageHtml || '<span class="muted">No stage logs.</span>';
          }

          function renderRunDetail(run, deliverables){
            const score = run.latest_scorecard ? `<pre>${esc(JSON.stringify(run.latest_scorecard, null, 2))}</pre>` : `<span class="muted">No score yet.</span>`;
            return `
              <div style="margin-bottom:12px;">
                <div><b>Run:</b> ${esc(run.id)}</div>
                <div><span class="pill">status: ${esc(run.status)}</span><span class="pill">stage: ${esc(run.current_stage || "-")}</span><span class="pill">mode: ${esc(run.pipeline_mode)}</span></div>
                <div class="muted">provider/model: ${esc(run.model_provider)} / ${esc(run.model_name)} | budget: ${esc(run.budget_used)}</div>
                <div class="muted">product_code: ${esc(run.product_code)} | industry_code: ${esc(run.industry_code)} | creative_preset: ${esc(run.creative_preset)}</div>
                <div class="muted">creative_specs: ${esc(JSON.stringify(run.creative_specs || {}))}</div>
              </div>
              ${renderDeliverables(deliverables)}
              <h3 style="margin-top:14px;">Stage Timeline</h3>
              <div class="timeline">${renderTimeline(run)}</div>
              <h3 style="margin-top:14px;">Latest Scorecard</h3>
              ${score}
            `;
          }

          async function selectRun(runId){
            currentRunId = runId;
            const [run, deliverables] = await Promise.all([
              api(`/runs/${runId}`),
              api(`/runs/${runId}/deliverables`).catch(() => ({ run_id: runId, deliverables: {}, score: {} }))
            ]);
            document.getElementById("run-detail").innerHTML = renderRunDetail(run, deliverables);
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
            sel.onchange = refreshModeHint;
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

          async function createRun(event){
            event.preventDefault();
            const msg = document.getElementById("create-msg");
            try {
              const businessContext = {
                product_description: document.getElementById("product_description").value,
                target_audience: document.getElementById("target_audience").value,
                key_value_props: toList(document.getElementById("key_value_props").value),
                primary_cta: document.getElementById("primary_cta").value,
                campaign_objective: document.getElementById("campaign_goal").value,
                price_range: document.getElementById("price_range").value,
                ...parseJsonObject(document.getElementById("business_context_extra").value),
              };
              const urlReferences = document.getElementById("url_references").value.split("\\n").map(s => s.trim()).filter(Boolean);
              const payload = new FormData();
              payload.append("workspace_name", document.getElementById("workspace_name").value);
              payload.append("project_name", document.getElementById("project_name").value);
              payload.append("product_name", document.getElementById("product_name").value);
              payload.append("product_code", document.getElementById("product_code").value);
              payload.append("industry_code", document.getElementById("industry_code").value);
              payload.append("campaign_name", document.getElementById("campaign_name").value);
              payload.append("channel", document.getElementById("channel").value);
              payload.append("objective", document.getElementById("objective").value);
              payload.append("creative_preset", document.getElementById("creative_preset").value);
              payload.append("creative_specs", JSON.stringify(buildCreativeSpecs()));
              payload.append("pipeline_mode", document.getElementById("pipeline_mode").value);
              payload.append("variant_count", String(Number(document.getElementById("variant_count").value || 8)));
              payload.append("category_tags", JSON.stringify(toList(document.getElementById("category_tags").value)));
              payload.append("url_references", JSON.stringify(urlReferences));
              payload.append("enable_research", document.getElementById("research_mode").value === "autonomous_web" ? "true" : "false");
              payload.append("manual_research_brief", document.getElementById("manual_research_brief").value);
              payload.append("business_context", JSON.stringify(businessContext));
              const files = document.getElementById("input_files").files;
              for (let i = 0; i < files.length; i++) payload.append("files", files[i]);
              const resp = await fetch("/runs/rich", { method: "POST", body: payload });
              if (!resp.ok) throw new Error(await resp.text());
              const run = await resp.json();
              msg.className = "status-msg status-ok";
              msg.textContent = `Created run ${run.id} (${run.pipeline_mode})`;
              await refreshRuns();
              await selectRun(run.id);
            } catch (err) {
              msg.className = "status-msg status-error";
              msg.textContent = `Create failed: ${err.message || err}`;
            }
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

          async function loadPersonas(){
            const list = await api("/personas");
            const box = document.getElementById("persona-list");
            const gm = list.find((p) => p.agent_name === "gm_orchestrator" || p.stage === "manager");
            const others = list.filter((p) => !gm || p.agent_name !== gm.agent_name);
            box.innerHTML = `
              <div class="muted">Total agents: ${list.length}</div>
              <div class="persona-chips" id="persona-gm-wrap"></div>
              ${gm && others.length ? '<div class="persona-divider"></div>' : ''}
              <div class="persona-chips" id="persona-other-wrap"></div>
            `;
            const gmWrap = document.getElementById("persona-gm-wrap");
            const otherWrap = document.getElementById("persona-other-wrap");
            const createPersonaButton = (p, extraClass = "") => {
              const b = document.createElement("button");
              b.textContent = `${p.display_name} (${p.stage})`;
              b.className = `persona-chip ${extraClass}`.trim();
              b.onclick = () => openPersona(p.agent_name);
              return b;
            };
            if (gm) {
              gmWrap.appendChild(createPersonaButton(gm, "persona-chip-gm"));
            }
            others.forEach((p) => {
              otherWrap.appendChild(createPersonaButton(p));
            });
          }

          async function openPersona(name){
            const p = await api(`/personas/${name}`);
            currentPersona = p.agent_name;
            const area = document.getElementById("persona-content");
            area.style.display = "block";
            area.value = p.content;
            document.getElementById("persona-save").style.display = "inline-block";
          }

          async function savePersona(){
            if(!currentPersona) return;
            const content = document.getElementById("persona-content").value;
            await api(`/personas/${currentPersona}`, { method:"PATCH", body: JSON.stringify({content, changed_by:"dashboard_ui"})});
            const msg = document.getElementById("persona-msg");
            msg.className = "status-msg status-ok";
            msg.textContent = `Saved ${currentPersona}`;
          }

          refreshResearchHint();
          refreshPresetHint();
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
          loadPersonas();
          setInterval(refreshRuns, 5000);
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
          .table-wrap {{ overflow: auto; border: 1px solid var(--line); border-radius: 12px; }}
          table {{ width: 100%; border-collapse: collapse; font-size: 13px; min-width: 920px; }}
          th, td {{ border-bottom: 1px solid #e8eee8; padding: 9px 10px; text-align: left; vertical-align: top; }}
          thead th {{ background: #f8fbf8; font-weight: 700; color: #295345; }}
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
        <main class="app-shell">
          <header class="hero">
            <div>
              <h1>Agent API Configs</h1>
              <div class="subtitle">Fallback rule: if agent config missing, use <b>default</b>.</div>
              <div class="subtitle">Security: only env var names are stored. Prefix required: <b>{API_KEY_ENV_PREFIX}</b>.</div>
              <div class="subtitle">Generation endpoint is unified in this table: <b>Generation Agent - Text / Image / Video</b>.</div>
            </div>
            <a class="nav-link" href="/dashboard">Back to Dashboard</a>
          </header>
          <section class="card">
            <div class="table-wrap">
              <table>
                <thead><tr><th>Agent</th><th>Provider</th><th>Model</th><th>Base URL</th><th>API Key Env</th><th>Env Status</th><th>Action</th></tr></thead>
                <tbody id="cfg-body"></tbody>
              </table>
            </div>
          </section>
        </main>
        <script>
          const personas = {personas_json};
          const existing = {configs_json};
          let envVars = {env_vars_json};
          const byAgent = Object.fromEntries(existing.map(c => [c.agent_name, c]));
          const baseRows = [{{ agent_name: "default", display_name: "Default Fallback", stage: "global" }}, ...personas];
          const rows = baseRows.flatMap((r) => {{
            if (r.agent_name !== "generation_agent") {{
              return [{{ row_key: `${{r.agent_name}}__text`, agent_name: r.agent_name, mode: "text", title: (r.display_name || r.agent_name), source: r.agent_name }}];
            }}
            return [
              {{ row_key: "generation_agent__text", agent_name: "generation_agent", mode: "text", title: "Generation Agent - Text", source: "generation_agent" }},
              {{ row_key: "generation_agent__image", agent_name: "generation_agent", mode: "image", title: "Generation Agent - Image", source: "generation_agent" }},
              {{ row_key: "generation_agent__video", agent_name: "generation_agent", mode: "video", title: "Generation Agent - Video", source: "generation_agent" }},
            ];
          }});
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
          function render() {{
            const body = document.getElementById("cfg-body");
            body.innerHTML = "";
            rows.forEach((r) => {{
              const cfg = byAgent[r.agent_name] || {{}};
              const provider = r.mode === "text" ? (cfg.provider_name || "") : (r.mode === "image" ? (cfg.image_provider_name || "") : (cfg.video_provider_name || ""));
              const model = r.mode === "text" ? (cfg.model_name || "") : (r.mode === "image" ? (cfg.image_model_name || "") : (cfg.video_model_name || ""));
              const baseUrl = r.mode === "text" ? (cfg.api_base_url || "") : (r.mode === "image" ? (cfg.image_api_base_url || "") : (cfg.video_api_base_url || ""));
              const keyEnv = r.mode === "text" ? (cfg.api_key_env || "") : (r.mode === "image" ? (cfg.image_api_key_env || "") : (cfg.video_api_key_env || ""));
              const keyFound = r.mode === "text" ? cfg.api_key_available : (r.mode === "image" ? cfg.image_api_key_available : cfg.video_api_key_available);
              const tr = document.createElement("tr");
              const envStatus = keyEnv
                ? (keyFound ? '<span class="badge">found</span>' : '<span class="badge badge-missing">missing</span>')
                : '<span class="muted">-</span>';
              tr.innerHTML = `
                <td>${{r.title}}<div class="muted">${{r.source}}</div></td>
                <td><input id="p-${{r.row_key}}" value="${{provider}}" /></td>
                <td><input id="m-${{r.row_key}}" value="${{model}}" /></td>
                <td><input id="b-${{r.row_key}}" value="${{baseUrl}}" /></td>
                <td><select id="k-${{r.row_key}}">${{envOptions(keyEnv)}}</select></td>
                <td>${{envStatus}}</td>
                <td><button onclick="save('${{r.row_key}}')">Save</button></td>`;
              body.appendChild(tr);
            }});
          }}
          async function save(rowKey) {{
            const row = rows.find((r) => r.row_key === rowKey);
            if (!row) return;
            const provider_name = document.getElementById(`p-${{rowKey}}`).value || null;
            const model_name = document.getElementById(`m-${{rowKey}}`).value || null;
            const api_base_url = document.getElementById(`b-${{rowKey}}`).value || null;
            const api_key_env = document.getElementById(`k-${{rowKey}}`).value || null;
            let payload = {{}};
            if (row.mode === "text") {{
              payload = {{ provider_name, model_name, api_base_url, api_key_env }};
            }} else if (row.mode === "image") {{
              payload = {{
                image_provider_name: provider_name,
                image_model_name: model_name,
                image_api_base_url: api_base_url,
                image_api_key_env: api_key_env
              }};
            }} else if (row.mode === "video") {{
              payload = {{
                video_provider_name: provider_name,
                video_model_name: model_name,
                video_api_base_url: api_base_url,
                video_api_key_env: api_key_env
              }};
            }}
            byAgent[row.agent_name] = await api(`/agent-configs/${{row.agent_name}}`, {{ method: "PATCH", body: JSON.stringify(payload) }});
            render();
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
            object-fit: cover;
            max-height: 220px;
            background:#f2f5fa;
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
                ? `<a href="${mediaUrl(item.uri)}" target="_blank"><img class="img-preview" src="${mediaUrl(item.uri)}" alt="asset"/></a>`
                : isVideo
                  ? `<video controls class="img-preview" src="${mediaUrl(item.uri)}"></video>`
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
    media_type = "application/octet-stream"
    guessed, _ = mimetypes.guess_type(str(requested))
    if guessed:
        media_type = guessed
    return FileResponse(path=str(requested), media_type=media_type)


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


@router.get("/creative-presets", response_model=dict[str, dict])
def get_creative_presets() -> dict[str, dict]:
    return list_creative_presets()


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


@router.post("/runs/rich", response_model=RunView)
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
    enable_research: bool = Form(False),
    manual_research_brief: str = Form(""),
    business_context: str = Form("{}"),
    category_tags: str = Form("[]"),
    url_references: str = Form("[]"),
    files: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
) -> RunView:
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
        enable_research=enable_research,
        manual_research_brief=manual_research_brief,
        business_context=_load_json_dict(business_context, "business_context"),
        category_tags=_load_json_list(category_tags, "category_tags"),
        context={"url_references": _load_json_list(url_references, "url_references")},
    )
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
    return _serialize_run(db, run)


@router.get("/runs/{run_id}", response_model=RunView)
def get_pipeline_run(run_id: str, db: Session = Depends(get_db)) -> RunView:
    try:
        run = get_run(db, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _serialize_run(db, run)


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


@router.get("/runs/{run_id}/variants", response_model=VariantsResponse)
def get_run_variants(run_id: str, db: Session = Depends(get_db)) -> VariantsResponse:
    try:
        get_run(db, run_id)
        data = run_variants(db, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return VariantsResponse(run_id=run_id, variants=data.get("variants", []), ranked=data.get("ranked", []))


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
            extra=payload.extra,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return _serialize_agent_config(row)

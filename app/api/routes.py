from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.agents.registry import stage_agent
from app.data.models import Artifact, PipelineRun, StageTask
from app.data.session import get_db
from app.orchestrator.state_machine import PIPELINE_STAGE_PLANS, PipelineMode
from app.schemas.api import (
    AgentApiConfigPatchRequest,
    AgentApiConfigView,
    DeliverablesResponse,
    FeedbackImportRequest,
    FeedbackImportResponse,
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
        campaign_id=run.campaign_id,
        market=run.market,
        locale=run.locale,
        model_provider=run.model_provider,
        model_name=run.model_name,
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


def _dashboard_html() -> str:
    return """
    <html>
      <head>
        <title>Crispy Dashboard</title>
        <style>
          body { font-family: ui-sans-serif, -apple-system, Segoe UI, Roboto, sans-serif; margin: 24px; color: #1a1d21; background:#f7f9fc; }
          .grid { display: grid; grid-template-columns: 1.3fr 1fr; gap: 18px; align-items: start; }
          .card { border: 1px solid #d9dce1; border-radius: 12px; padding: 16px; background: #fff; }
          table { width: 100%; border-collapse: collapse; font-size: 13px; }
          th, td { border-bottom: 1px solid #eceef2; padding: 8px; text-align: left; vertical-align: top; }
          textarea, input, select { width: 100%; padding: 8px; border-radius: 8px; border: 1px solid #c8cfda; margin: 4px 0 10px 0; box-sizing: border-box; background: #fff; }
          button { padding: 8px 12px; border-radius: 8px; border: 1px solid #bcc4cf; background: #f4f7fb; cursor: pointer; }
          .muted { color: #5a6270; font-size: 12px; }
          .detail-scroll { max-height: 640px; overflow-y: auto; border:1px solid #eef1f5; border-radius: 10px; padding: 10px; background:#fdfefe; }
          .row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
          .stage-card { border: 1px solid #e8edf4; border-radius: 10px; padding: 10px; margin-bottom: 10px; background: #fff; }
          .stage-title { font-weight: 600; margin-bottom: 6px; }
          .pill { display:inline-block; padding:2px 8px; border-radius:20px; font-size:12px; border:1px solid #d6deea; margin-right:6px; }
          .hint { padding: 8px 10px; border: 1px solid #e8edf4; border-radius: 8px; background: #f9fbff; margin-bottom: 8px; }
        </style>
      </head>
      <body>
        <h1>Crispy Dashboard</h1>
        <p class="muted">Create run now uses multipart upload and supports mode-specific pipelines. Agent API config: <a href="/dashboard/agent-apis">/dashboard/agent-apis</a></p>
        <div class="grid">
          <section class="card">
            <h2>Runs</h2>
            <div style="margin-bottom:10px;">
              <button onclick="refreshRuns()">Refresh</button>
              <button onclick="advanceRun()">Advance</button>
              <button onclick="rejectRun()">Reject</button>
            </div>
            <table>
              <thead><tr><th>Run ID</th><th>Status</th><th>Stage</th><th>Mode</th><th>Updated</th></tr></thead>
              <tbody id="runs-body"></tbody>
            </table>
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
                <div><label>Pipeline Mode</label><select id="pipeline_mode"></select></div>
                <div><label>Variant Count</label><input id="variant_count" type="number" min="1" max="16" value="8" /></div>
              </div>
              <div id="mode-summary" class="hint muted">Loading pipeline modes...</div>
              <div class="row">
                <div><label>Provider</label><input id="model_provider" value="openai" /></div>
                <div><label>Model</label><input id="model_name" value="gpt-4.1" /></div>
              </div>
              <div class="row">
                <div><label>Channel</label><input id="channel" value="meta" /></div>
                <div><label>Objective</label><input id="objective" value="conversions" /></div>
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
              <button type="submit">Create Run</button>
            </form>
            <div id="create-msg" class="muted"></div>
          </section>
        </div>
        <div class="grid" style="margin-top:20px;">
          <section class="card">
            <h2>Run Detail</h2>
            <div id="run-detail" class="detail-scroll">Select a run.</div>
          </section>
          <section class="card">
            <h2>Persona Manager</h2>
            <div id="persona-list"></div>
            <textarea id="persona-content" rows="12" style="display:none"></textarea>
            <button id="persona-save" style="display:none" onclick="savePersona()">Save Persona</button>
          </section>
        </div>
        <script>
          let currentRunId = null;
          let currentPersona = null;
          let pipelineModes = [];

          function esc(v){ return String(v ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;");}
          function toList(raw){ return String(raw || "").split(",").map(s => s.trim()).filter(Boolean); }
          function parseJsonObject(raw){
            if (!raw || !raw.trim()) return {};
            try { return JSON.parse(raw); } catch (_e) { throw new Error("Advanced Business Context JSON is invalid."); }
          }

          async function api(path, options = {}) {
            const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
            if (!res.ok) { throw new Error(await res.text()); }
            return res.headers.get("content-type")?.includes("application/json") ? res.json() : res.text();
          }

          async function refreshRuns() {
            const rows = await api("/runs");
            const body = document.getElementById("runs-body");
            body.innerHTML = "";
            rows.forEach((r) => {
              const tr = document.createElement("tr");
              tr.innerHTML = `<td><a href="#" onclick="selectRun('${r.id}');return false;">${r.id.slice(0,8)}</a></td><td>${esc(r.status)}</td><td>${esc(r.current_stage||"-")}</td><td>${esc(r.pipeline_mode)}</td><td>${esc(r.updated_at)}</td>`;
              body.appendChild(tr);
            });
          }

          function renderRunDetail(run){
            const stageHtml = run.stage_tasks.map((task) => {
              const agent = task.metadata_json?.agent_name || "-";
              return `
                <article class="stage-card">
                  <div class="stage-title">${esc(task.stage_name)}</div>
                  <div>
                    <span class="pill">status: ${esc(task.status)}</span>
                    <span class="pill">attempt: ${esc(task.attempt)}</span>
                    <span class="pill">agent: ${esc(agent)}</span>
                  </div>
                  <div class="muted">started: ${esc(task.started_at || "-")} | completed: ${esc(task.completed_at || "-")}</div>
                  <div class="muted">review: ${esc(task.review_notes || "-")}</div>
                  <details>
                    <summary>Output JSON</summary>
                    <pre>${esc(JSON.stringify(task.output_payload || {}, null, 2))}</pre>
                  </details>
                </article>
              `;
            }).join("");
            const score = run.latest_scorecard ? `<pre>${esc(JSON.stringify(run.latest_scorecard, null, 2))}</pre>` : `<span class="muted">No score yet.</span>`;
            return `
              <div style="margin-bottom:12px;">
                <div><b>Run:</b> ${esc(run.id)}</div>
                <div><span class="pill">status: ${esc(run.status)}</span><span class="pill">stage: ${esc(run.current_stage || "-")}</span><span class="pill">mode: ${esc(run.pipeline_mode)}</span></div>
                <div class="muted">provider/model: ${esc(run.model_provider)} / ${esc(run.model_name)} | budget: ${esc(run.budget_used)}</div>
              </div>
              <h3>Stage Logs</h3>
              ${stageHtml || '<span class="muted">No stage logs.</span>'}
              <h3>Latest Scorecard</h3>
              ${score}
            `;
          }

          async function selectRun(runId){
            currentRunId = runId;
            const run = await api(`/runs/${runId}`);
            document.getElementById("run-detail").innerHTML = renderRunDetail(run);
          }

          async function loadPipelineModes(){
            pipelineModes = await api("/pipeline-modes");
            const sel = document.getElementById("pipeline_mode");
            sel.innerHTML = "";
            pipelineModes.forEach((m) => {
              const opt = document.createElement("option");
              opt.value = m.mode;
              opt.textContent = `${m.display_name} (${m.agent_count} agents)`;
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
              payload.append("campaign_name", document.getElementById("campaign_name").value);
              payload.append("channel", document.getElementById("channel").value);
              payload.append("objective", document.getElementById("objective").value);
              payload.append("model_provider", document.getElementById("model_provider").value);
              payload.append("model_name", document.getElementById("model_name").value);
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
              document.getElementById("create-msg").textContent = `Created run ${run.id} (${run.pipeline_mode})`;
              await refreshRuns();
              await selectRun(run.id);
            } catch (err) {
              document.getElementById("create-msg").textContent = `Create failed: ${err.message || err}`;
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
            box.innerHTML = `<div class="muted">Total agents: ${list.length}</div>`;
            list.forEach((p)=>{
              const b=document.createElement("button");
              b.textContent=`${p.display_name} (${p.stage})`;
              b.style.margin = "4px 6px 4px 0";
              b.onclick=()=>openPersona(p.agent_name);
              box.appendChild(b);
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
          }

          refreshResearchHint();
          loadPipelineModes();
          refreshRuns();
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
        <style>
          body {{ font-family: ui-sans-serif, -apple-system, Segoe UI, Roboto, sans-serif; margin: 24px; color: #1a1d21; }}
          table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
          th, td {{ border-bottom: 1px solid #eceef2; padding: 8px; text-align: left; vertical-align: top; }}
          input, select {{ width: 100%; padding: 6px; border-radius: 6px; border: 1px solid #c8cfda; box-sizing: border-box; }}
          button {{ padding: 6px 10px; border-radius: 8px; border: 1px solid #bbc2cc; background: #f7f9fc; cursor: pointer; }}
          .muted {{ color: #5a6270; font-size: 12px; }}
        </style>
      </head>
      <body>
        <h1>Agent API Configs</h1>
        <p class="muted">Fallback rule: if agent config missing, use <b>default</b>.</p>
        <p class="muted">Security: only env var names are stored. Prefix required: <b>{API_KEY_ENV_PREFIX}</b>.</p>
        <p><a href="/dashboard">Back to Dashboard</a></p>
        <table>
          <thead><tr><th>Agent</th><th>Provider</th><th>Model</th><th>Base URL</th><th>API Key Env</th><th>Env Status</th><th>Action</th></tr></thead>
          <tbody id="cfg-body"></tbody>
        </table>
        <script>
          const personas = {personas_json};
          const existing = {configs_json};
          let envVars = {env_vars_json};
          const byAgent = Object.fromEntries(existing.map(c => [c.agent_name, c]));
          const rows = [{{ agent_name: "default", display_name: "Default Fallback", stage: "global" }}, ...personas];
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
              const tr = document.createElement("tr");
              tr.innerHTML = `
                <td>${{r.display_name || r.agent_name}}<div class="muted">${{r.agent_name}}</div></td>
                <td><input id="p-${{r.agent_name}}" value="${{cfg.provider_name || ""}}" /></td>
                <td><input id="m-${{r.agent_name}}" value="${{cfg.model_name || ""}}" /></td>
                <td><input id="b-${{r.agent_name}}" value="${{cfg.api_base_url || ""}}" /></td>
                <td><select id="k-${{r.agent_name}}">${{envOptions(cfg.api_key_env || "")}}</select></td>
                <td>${{cfg.api_key_env ? (cfg.api_key_available ? "found" : "missing") : "-"}}</td>
                <td><button onclick="save('${{r.agent_name}}')">Save</button></td>`;
              body.appendChild(tr);
            }});
          }}
          async function save(agentName) {{
            const payload = {{
              provider_name: document.getElementById(`p-${{agentName}}`).value || null,
              model_name: document.getElementById(`m-${{agentName}}`).value || null,
              api_base_url: document.getElementById(`b-${{agentName}}`).value || null,
              api_key_env: document.getElementById(`k-${{agentName}}`).value || null
            }};
            byAgent[agentName] = await api(`/agent-configs/${{agentName}}`, {{ method: "PATCH", body: JSON.stringify(payload) }});
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


@router.get("/", response_class=HTMLResponse)
def dashboard_root() -> str:
    return _dashboard_html()


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page() -> str:
    return _dashboard_html()


@router.get("/dashboard/agent-apis", response_class=HTMLResponse)
def dashboard_agent_apis(db: Session = Depends(get_db)) -> str:
    personas = [PersonaMeta(**row).model_dump(mode="json") for row in list_persona_catalog()]
    configs = [
        AgentApiConfigView(
            agent_name=row.agent_name,
            provider_name=row.provider_name,
            model_name=row.model_name,
            api_base_url=row.api_base_url,
            api_key_env=row.api_key_env,
            api_key_available=api_key_available(row.api_key_env),
            extra=row.extra or {},
            is_default=row.agent_name == "default",
            updated_at=row.updated_at,
        ).model_dump(mode="json")
        for row in list_agent_configs(db)
    ]
    db.commit()
    return _agent_api_dashboard_html(
        personas_json=json.dumps(personas, ensure_ascii=False).replace("</", "<\\/"),
        configs_json=json.dumps(configs, ensure_ascii=False).replace("</", "<\\/"),
        env_vars_json=json.dumps(list_api_key_env_names(), ensure_ascii=False).replace("</", "<\\/"),
    )


@router.get("/pipeline-modes", response_model=list[PipelineModeView])
def list_pipeline_modes() -> list[PipelineModeView]:
    return _pipeline_mode_views()


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
            updated_at=run.updated_at,
        )
        for run in runs
    ]


@router.post("/runs", response_model=RunView)
def create_pipeline_run(payload: RunCreateRequest, db: Session = Depends(get_db)) -> RunView:
    run = create_run(db, payload)
    db.commit()
    db.refresh(run)
    return _serialize_run(db, run)


@router.post("/runs/rich", response_model=RunView)
async def create_pipeline_run_rich(
    workspace_name: str = Form(...),
    project_name: str = Form(...),
    product_name: str = Form(...),
    campaign_name: str = Form(...),
    channel: str = Form("meta"),
    objective: str = Form("conversions"),
    market: str = Form("US"),
    locale: str = Form("en-US"),
    variant_count: int = Form(8),
    model_provider: str = Form("openai"),
    model_name: str = Form("gpt-4.1"),
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
        campaign_name=campaign_name,
        channel=channel,
        objective=objective,
        market=market,
        locale=locale,
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
    run = create_run(db, payload)
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
    return [
        AgentApiConfigView(
            agent_name=row.agent_name,
            provider_name=row.provider_name,
            model_name=row.model_name,
            api_base_url=row.api_base_url,
            api_key_env=row.api_key_env,
            api_key_available=api_key_available(row.api_key_env),
            extra=row.extra or {},
            is_default=row.agent_name == "default",
            updated_at=row.updated_at,
        )
        for row in rows
    ]


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
            extra=payload.extra,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return AgentApiConfigView(
        agent_name=row.agent_name,
        provider_name=row.provider_name,
        model_name=row.model_name,
        api_base_url=row.api_base_url,
        api_key_env=row.api_key_env,
        api_key_available=api_key_available(row.api_key_env),
        extra=row.extra or {},
        is_default=row.agent_name == "default",
        updated_at=row.updated_at,
    )

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.data.models import PipelineRun, StageTask
from app.data.session import get_db
from app.schemas.api import (
    AgentApiConfigPatchRequest,
    AgentApiConfigView,
    FeedbackImportRequest,
    FeedbackImportResponse,
    LeaderboardItem,
    LeaderboardResponse,
    PersonaMeta,
    PersonaPatchRequest,
    PersonaView,
    ReviewActionRequest,
    RunCreateRequest,
    RunSummary,
    RunView,
    StageTaskView,
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
from app.services.personas import get_persona, list_persona_catalog, persona_info, update_persona
from app.services.runs import approve_stage, create_run, get_run, latest_scorecard, reject_stage


router = APIRouter()


def _serialize_run(db: Session, run: PipelineRun) -> RunView:
    tasks = db.scalars(
        select(StageTask).where(StageTask.run_id == run.id).order_by(StageTask.created_at.asc())
    ).all()
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
        budget_used=run.budget_used,
        variant_count=run.variant_count,
        created_at=run.created_at,
        updated_at=run.updated_at,
        stage_tasks=task_views,
        latest_scorecard=scorecard,
        latest_forecast=forecast,
    )


def _dashboard_html() -> str:
    return """
    <html>
      <head>
        <title>Crispy Dashboard</title>
        <style>
          body { font-family: ui-sans-serif, -apple-system, Segoe UI, Roboto, sans-serif; margin: 24px; color: #1a1d21; background:#fafbfc; }
          .grid { display: grid; grid-template-columns: 1.4fr 1fr; gap: 20px; align-items: start; }
          .card { border: 1px solid #d9dce1; border-radius: 12px; padding: 16px; background: #fff; }
          h1, h2, h3 { margin-top: 0; }
          table { width: 100%; border-collapse: collapse; font-size: 13px; }
          th, td { border-bottom: 1px solid #eceef2; padding: 8px; text-align: left; vertical-align: top; }
          button { margin-right: 8px; padding: 8px 10px; border-radius: 8px; border: 1px solid #bbc2cc; background: #f7f9fc; cursor: pointer; }
          textarea, input { width: 100%; padding: 8px; border-radius: 8px; border: 1px solid #c8cfda; margin: 4px 0 10px 0; box-sizing: border-box; background: #fff; }
          label { display:block; font-size:12px; color:#334155; margin-top:6px; font-weight:600; }
          .muted { color: #5a6270; font-size: 12px; }
          .pill { display: inline-block; border-radius: 999px; padding: 2px 8px; font-size: 11px; background: #edf3ff; margin-right: 6px; }
          .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
          .row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
          .actions { margin: 10px 0; }
          .detail-scroll { max-height: 560px; overflow-y: auto; border:1px solid #eef1f5; border-radius: 10px; padding: 10px; background:#fdfefe; }
          .run-summary { border:1px solid #edf2f7; border-radius:8px; padding:8px 10px; margin-bottom:10px; background:#f8fafc; }
          .log-item { border:1px solid #e6ebf0; border-radius:10px; padding:10px; margin-bottom:10px; background:#fff; }
          .log-head { display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; }
          .log-meta { color:#4b5563; font-size:12px; margin:2px 0; }
          .status { border-radius:999px; padding:2px 8px; font-size:11px; text-transform:uppercase; font-weight:600; }
          .status-running { background:#fff7ed; color:#9a3412; }
          .status-waiting_review { background:#eff6ff; color:#1d4ed8; }
          .status-approved, .status-completed { background:#ecfdf5; color:#047857; }
          .status-rejected, .status-failed { background:#fef2f2; color:#b91c1c; }
          .status-queued, .status-draft { background:#f3f4f6; color:#374151; }
          details summary { cursor:pointer; color:#1f4f99; margin-top:6px; }
          pre { white-space: pre-wrap; word-break: break-word; margin:8px 0 0 0; }
        </style>
      </head>
      <body>
        <h1>Crispy Dashboard</h1>
        <p class="muted">半自动可验证 MVP：四阶段人工闸门 + 反馈闭环。Agent API 配置页: <a href="/dashboard/agent-apis">/dashboard/agent-apis</a></p>
        <div class="grid">
          <section class="card">
            <h2>Runs</h2>
            <div class="actions">
              <button onclick="refreshRuns()">Refresh</button>
              <button onclick="advanceRun()">Advance Current Stage</button>
              <button onclick="rejectRun()">Reject Current Stage</button>
            </div>
            <table>
              <thead><tr><th>Run ID</th><th>Status</th><th>Stage</th><th>Updated</th></tr></thead>
              <tbody id="runs-body"></tbody>
            </table>
          </section>
          <section class="card">
            <h2>Create Run</h2>
            <form onsubmit="createRun(event)">
              <label for="workspace_name">Workspace Name</label>
              <input id="workspace_name" placeholder="workspace_name" value="workspace_demo" />
              <label for="project_name">Project Name</label>
              <input id="project_name" placeholder="project_name" value="project_demo" />
              <label for="product_name">Product Name</label>
              <input id="product_name" placeholder="product_name" value="pet_product" />
              <label for="campaign_name">Campaign Name</label>
              <input id="campaign_name" placeholder="campaign_name" value="meta_campaign_1" />
              <div class="row">
                <div>
                  <label for="model_provider">Default Provider</label>
                  <input id="model_provider" placeholder="model_provider" value="kimi" />
                </div>
                <div>
                  <label for="model_name">Default Model</label>
                  <input id="model_name" placeholder="model_name" value="kimi-default-text" />
                </div>
              </div>
              <button type="submit">Create</button>
            </form>
            <div id="create-msg" class="muted"></div>
          </section>
        </div>
        <div class="grid" style="margin-top:20px;">
          <section class="card">
            <h2>Run Detail</h2>
            <div id="run-detail" class="mono detail-scroll">Select a run to inspect stage logs.</div>
          </section>
          <section class="card">
            <h2>Persona Manager</h2>
            <div id="persona-list" class="muted">Loading personas...</div>
            <div id="persona-editor" style="margin-top:10px; display:none;">
              <div class="muted" id="persona-meta"></div>
              <textarea id="persona-content" rows="14"></textarea>
              <button onclick="savePersona()">Save Persona</button>
            </div>
          </section>
        </div>
        <script>
          let currentRunId = null;
          let currentPersona = null;

          function esc(value) {
            return String(value ?? "")
              .replaceAll("&", "&amp;")
              .replaceAll("<", "&lt;")
              .replaceAll(">", "&gt;");
          }

          function statusBadge(status) {
            const safe = esc(status || "unknown");
            return `<span class="status status-${safe}">${safe}</span>`;
          }

          function prettyTime(value) {
            if (!value) return "-";
            try { return new Date(value).toLocaleString(); } catch { return value; }
          }

          function truncateJson(value, maxLen = 1800) {
            const text = JSON.stringify(value || {}, null, 2);
            if (text.length <= maxLen) return text;
            return `${text.slice(0, maxLen)}\\n...<truncated>`;
          }

          async function api(path, options = {}) {
            const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
            if (!res.ok) {
              const txt = await res.text();
              throw new Error(txt || res.statusText);
            }
            return res.headers.get("content-type")?.includes("application/json") ? res.json() : res.text();
          }

          async function refreshRuns() {
            const rows = await api("/runs");
            const body = document.getElementById("runs-body");
            body.innerHTML = "";
            rows.forEach((r) => {
              const tr = document.createElement("tr");
              tr.innerHTML = `<td><a href="#" onclick="selectRun('${r.id}');return false;">${r.id.slice(0, 8)}</a></td>
                              <td>${statusBadge(r.status)}</td><td>${esc(r.current_stage || "-")}</td><td>${prettyTime(r.updated_at)}</td>`;
              body.appendChild(tr);
            });
          }

          function renderRunDetail(run) {
            const score = run.latest_scorecard?.total_score;
            const conf = run.latest_forecast?.confidence_0_1;
            const summary = `
              <div class="run-summary">
                <div><b>Run:</b> ${esc(run.id)} | <b>Status:</b> ${statusBadge(run.status)} | <b>Current Stage:</b> ${esc(run.current_stage || "-")}</div>
                <div class="log-meta"><b>Budget Used:</b> ${esc(run.budget_used)} | <b>Variant Count:</b> ${esc(run.variant_count)} | <b>Updated:</b> ${prettyTime(run.updated_at)}</div>
                <div class="log-meta"><b>Score:</b> ${score ?? "-"} | <b>Forecast Confidence:</b> ${conf ?? "-"}</div>
              </div>`;

            const logs = (run.stage_tasks || []).map((task) => {
              const resolved = task.metadata_json?.resolved_api || {};
              const outputText = esc(truncateJson(task.output_payload));
              const review = task.review_notes ? `<div class="log-meta"><b>Review:</b> ${esc(task.review_notes)}</div>` : "";
              const err = task.error_message ? `<div class="log-meta"><b>Error:</b> ${esc(task.error_message)}</div>` : "";
              const keyState = resolved.api_key_env
                ? `<div class="log-meta"><b>API Key Env:</b> ${esc(resolved.api_key_env)} (${resolved.api_key_available ? "found" : "missing"})</div>`
                : `<div class="log-meta"><b>API Key Env:</b> -</div>`;
              return `
                <article class="log-item">
                  <div class="log-head">
                    <div><b>${esc(task.stage_name).toUpperCase()}</b> #${esc(task.attempt)}</div>
                    <div>${statusBadge(task.status)}</div>
                  </div>
                  <div class="log-meta"><b>Start:</b> ${prettyTime(task.started_at)} | <b>End:</b> ${prettyTime(task.completed_at)}</div>
                  <div class="log-meta"><b>Provider/Model:</b> ${esc(resolved.provider_name || "-")} / ${esc(resolved.model_name || "-")} (${esc(resolved.source || "run_default")})</div>
                  ${keyState}
                  ${review}
                  ${err}
                  <details>
                    <summary>Stage Output (truncated)</summary>
                    <pre>${outputText}</pre>
                  </details>
                </article>`;
            }).join("");
            return summary + logs;
          }

          async function selectRun(runId, preserveScroll = false) {
            currentRunId = runId;
            const run = await api(`/runs/${runId}`);
            const panel = document.getElementById("run-detail");
            const shouldStickBottom = preserveScroll || Math.abs((panel.scrollHeight - panel.scrollTop - panel.clientHeight)) < 24;
            panel.innerHTML = renderRunDetail(run);
            if (shouldStickBottom) {
              panel.scrollTop = panel.scrollHeight;
            }
          }

          async function createRun(event) {
            event.preventDefault();
            const payload = {
              workspace_name: document.getElementById("workspace_name").value,
              project_name: document.getElementById("project_name").value,
              product_name: document.getElementById("product_name").value,
              campaign_name: document.getElementById("campaign_name").value,
              model_provider: document.getElementById("model_provider").value,
              model_name: document.getElementById("model_name").value,
            };
            const run = await api("/runs", { method: "POST", body: JSON.stringify(payload) });
            document.getElementById("create-msg").textContent = `Created run ${run.id}`;
            await refreshRuns();
            await selectRun(run.id);
          }

          async function advanceRun() {
            if (!currentRunId) return;
            await api(`/runs/${currentRunId}/advance`, { method: "POST", body: JSON.stringify({ notes: "approved_in_dashboard" }) });
            await selectRun(currentRunId);
            await refreshRuns();
          }

          async function rejectRun() {
            if (!currentRunId) return;
            await api(`/runs/${currentRunId}/reject`, { method: "POST", body: JSON.stringify({ notes: "rejected_in_dashboard" }) });
            await selectRun(currentRunId);
            await refreshRuns();
          }

          async function loadPersonas() {
            const list = await api("/personas");
            const container = document.getElementById("persona-list");
            container.innerHTML = "";
            list.forEach((p) => {
              const btn = document.createElement("button");
              btn.textContent = `${p.display_name} (${p.stage})`;
              btn.onclick = () => openPersona(p.agent_name);
              container.appendChild(btn);
            });
          }

          async function openPersona(agentName) {
            const p = await api(`/personas/${agentName}`);
            currentPersona = p.agent_name;
            document.getElementById("persona-editor").style.display = "block";
            document.getElementById("persona-meta").innerHTML =
              `<span class="pill">${p.display_name || p.agent_name}</span><span class="pill">v${p.version}</span><span class="pill">${p.stage || "n/a"}</span>`;
            document.getElementById("persona-content").value = p.content;
          }

          async function savePersona() {
            if (!currentPersona) return;
            const content = document.getElementById("persona-content").value;
            await api(`/personas/${currentPersona}`, { method: "PATCH", body: JSON.stringify({ content, changed_by: "dashboard_ui" }) });
            await openPersona(currentPersona);
          }

          refreshRuns();
          loadPersonas();
          setInterval(async () => {
            await refreshRuns();
            if (currentRunId) await selectRun(currentRunId, true);
          }, 5000);
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
        <p class="muted">规则：若单 Agent 配置为空或不存在，则自动使用 <b>default</b> 配置。</p>
        <p class="muted">安全策略：系统只存 <b>API Key Env 变量名</b>，不会存明文 API Key；执行时从系统环境变量读取。</p>
        <p class="muted">命名规则：环境变量前缀为 <b>{API_KEY_ENV_PREFIX}</b>，页面下拉列表会自动识别该前缀的变量。</p>
        <p><a href="/dashboard">Back to Dashboard</a></p>
        <table>
          <thead><tr><th>Agent</th><th>Provider</th><th>Model</th><th>Base URL</th><th>API Key Env (Name Only)</th><th>Env Status</th><th>Action</th></tr></thead>
          <tbody id="cfg-body"></tbody>
        </table>
        <script>
          const personas = {personas_json};
          const existing = {configs_json};
          const bootstrapEnvVars = {env_vars_json};
          let envVars = [...bootstrapEnvVars];
          const byAgent = Object.fromEntries(existing.map(c => [c.agent_name, c]));
          const rows = [{{ agent_name: "default", display_name: "Default Fallback", stage: "global" }}, ...personas];

          async function api(path, options = {{}}) {{
            const res = await fetch(path, {{ headers: {{ "Content-Type": "application/json" }}, ...options }});
            if (!res.ok) {{
              const txt = await res.text();
              throw new Error(txt || res.statusText);
            }}
            return res.json();
          }}

          function envOptions(selected) {{
            const names = [...envVars];
            if (selected && !names.includes(selected)) {{
              names.unshift(selected);
            }}
            const base = ['<option value="">(none)</option>'];
            names.forEach((name) => {{
              const selectedAttr = selected === name ? " selected" : "";
              base.push(`<option value="${{name}}"${{selectedAttr}}>${{name}}</option>`);
            }});
            return base.join("");
          }}

          function render() {{
            const body = document.getElementById("cfg-body");
            body.innerHTML = "";
            rows.forEach((r) => {{
              const cfg = byAgent[r.agent_name] || {{}};
              const tr = document.createElement("tr");
              tr.innerHTML = `
                <td>${{r.display_name || r.agent_name}}<div class="muted">${{r.agent_name}} / ${{r.stage || "-"}}</div></td>
                <td><input id="p-${{r.agent_name}}" value="${{cfg.provider_name || ""}}" placeholder="kimi"/></td>
                <td><input id="m-${{r.agent_name}}" value="${{cfg.model_name || ""}}" placeholder="kimi-default-text"/></td>
                <td><input id="b-${{r.agent_name}}" value="${{cfg.api_base_url || ""}}" placeholder="https://api.vendor.com/v1"/></td>
                <td><select id="k-${{r.agent_name}}">${{envOptions(cfg.api_key_env || "")}}</select></td>
                <td>${{cfg.api_key_env ? (cfg.api_key_available ? "found" : "missing") : "-"}}</td>
                <td><button onclick="save('${{r.agent_name}}')">Save</button></td>
              `;
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
            const updated = await api(`/agent-configs/${{agentName}}`, {{ method: "PATCH", body: JSON.stringify(payload) }});
            byAgent[agentName] = updated;
          }}

          async function init() {{
            try {{
              envVars = await api("/agent-configs/env-vars");
            }} catch (_err) {{
              envVars = [...bootstrapEnvVars];
            }}
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
    env_vars = list_api_key_env_names()
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
    personas_json = json.dumps(personas, ensure_ascii=False).replace("</", "<\\/")
    configs_json = json.dumps(configs, ensure_ascii=False).replace("</", "<\\/")
    env_vars_json = json.dumps(env_vars, ensure_ascii=False).replace("</", "<\\/")
    return _agent_api_dashboard_html(personas_json=personas_json, configs_json=configs_json, env_vars_json=env_vars_json)


@router.get("/runs", response_model=list[RunSummary])
def list_runs(db: Session = Depends(get_db)) -> list[RunSummary]:
    runs = db.scalars(select(PipelineRun).order_by(desc(PipelineRun.created_at)).limit(50)).all()
    return [
        RunSummary(
            id=run.id,
            status=run.status,
            current_stage=run.current_stage,
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


@router.get("/runs/{run_id}", response_model=RunView)
def get_pipeline_run(run_id: str, db: Session = Depends(get_db)) -> RunView:
    try:
        run = get_run(db, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _serialize_run(db, run)


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
        db,
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
def patch_agent_persona(
    agent_name: str,
    payload: PersonaPatchRequest,
    db: Session = Depends(get_db),
) -> PersonaView:
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
def patch_agent_config(
    agent_name: str,
    payload: AgentApiConfigPatchRequest,
    db: Session = Depends(get_db),
) -> AgentApiConfigView:
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

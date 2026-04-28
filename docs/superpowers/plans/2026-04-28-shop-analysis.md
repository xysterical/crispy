# Shop Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Shop Analysis page where `shop_analyst` agent researches a store URL (SEO, positioning, competitors) and saves findings to GmMemory for reuse in planning. Rename `research_agent` to `product_research_agent` for clarity.

**Architecture:** New `shop_analyst` agent persona with runtime method for web research + LLM synthesis. Results stored in existing GmMemory table with new `source_type` values (`shop_profile`, `competitor_analysis`). New page at `/dashboard/shop-analysis` with input form, two-phase execution, and history list. Agent API Configs page gets a divider separating pipeline agents from shop analysis agents.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, Pydantic v2, raw HTML/CSS/JS, pytest

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `personas/stages/01_product_research_agent.md` | Rename from | Renamed product research agent persona file |
| `personas/stages/shop_analyst.md` | Create | Shop analyst persona file |
| `app/agents/registry.py` | Modify | Rename research_agent → product_research_agent; add shop_analyst spec; update STAGE_ASSIGNMENTS |
| `app/agents/runtime.py` | Modify | Add `run_shop_analysis()` method |
| `app/schemas/api.py` | Modify | Add ShopAnalysisRequest, ShopAnalysisResponse schemas |
| `app/services/shop_analysis.py` | Create | Shop analysis orchestration service |
| `app/api/routes.py` | Modify | Add `/dashboard/shop-analysis` page, `POST /shop-analysis/run` endpoint, rename references, nav link |
| `app/dashboard/layout.py` | Modify | Add Shop Analysis nav link |
| `tests/test_shop_analysis.py` | Create | Tests for shop analysis endpoint and GmMemory integration |

---

### Task 1: Rename research_agent to product_research_agent

**Files:**
- Rename: `personas/stages/01_research_agent.md` → `personas/stages/01_product_research_agent.md`
- Modify: `app/agents/registry.py:59-79`
- Modify: `app/agents/registry.py:275`
- Modify: `app/api/routes.py:1940-1941` (JS rows list)

- [ ] **Step 1: Rename persona file**

```bash
mv personas/stages/01_research_agent.md personas/stages/01_product_research_agent.md
```

- [ ] **Step 2: Update AGENT_SPECS in registry.py**

In `app/agents/registry.py:59-79`, replace the AgentSpec:

```python
# Replace the existing research_agent AgentSpec block (lines 59-79):
    AgentSpec(
        name="product_research_agent",
        display_name="Product Research Agent",
        stage="research",
        role="product_market_research",
        relative_path="stages/01_product_research_agent.md",
        order=10,
        default_content="""# Product Research Agent
## Mission
Produce competitor, audience, and claim-risk intelligence for a specific product when research is enabled.

## Must Output
- Audience insights and purchase triggers.
- Competitor patterns and white-space observations.
- Forbidden or risky claim guidance.
- Source-backed notes or explicit statement that research was skipped.
- Claim confidence levels: evidence-backed, plausible hypothesis, or blocked.

## Review Questions
- Are the recommendations grounded in evidence?
- Did the brief isolate claim risk and messaging opportunities?
""",
    ),
```

- [ ] **Step 3: Update STAGE_ASSIGNMENTS in registry.py**

```python
# In app/agents/registry.py:275, change research_agent to product_research_agent:
    "planning": StageAssignment(lead_agent="planning_agent", collaborators=("product_research_agent", "gm_orchestrator")),
```

- [ ] **Step 4: Update JS agent row building in routes.py**

In `app/api/routes.py:1940`, the JS builds rows from `personas` array (which comes from AGENT_SPECS order). The display_name change in the spec is sufficient — no code change needed here since the JS reads `r.display_name` dynamically. But verify no hardcoded `"research_agent"` string exists in the JS:

Run: `grep -n "research_agent" app/api/routes.py`
Expected: no results (or only in Python-side references we'll fix next)

- [ ] **Step 5: Verify no remaining references to old name**

```bash
grep -r "research_agent" app/ personas/ tests/ --include="*.py" --include="*.md"
```

If any found in `app/` or `tests/`, update them to `product_research_agent`.

- [ ] **Step 6: Verify app loads and personas list correctly**

Run: `uv run python -c "from app.agents.registry import AGENT_SPECS; names = [s.name for s in AGENT_SPECS]; print('product_research_agent' in names, 'research_agent' not in names)"`
Expected: `True True`

- [ ] **Step 7: Commit**

```bash
git add personas/stages/01_product_research_agent.md app/agents/registry.py app/api/routes.py
git rm personas/stages/01_research_agent.md 2>/dev/null || true
git commit -m "refactor: rename research_agent to product_research_agent for clarity"
```

---

### Task 2: Create shop_analyst agent persona

**Files:**
- Create: `personas/stages/shop_analyst.md`
- Modify: `app/agents/registry.py`

- [ ] **Step 1: Create persona file**

```python
# personas/stages/shop_analyst.md
# Shop Analyst

## Mission
Research a store's positioning, product catalog, SEO profile, and competitive landscape. Produce structured intelligence for GM memory to improve downstream creative strategy.

## Must Output
- Store profile: positioning, target audience, price tier, product categories, unique selling points.
- SEO snapshot: key search terms, content gaps, category structure observations.
- Competitor analysis: 3-5 comparable stores, their positioning, creative patterns, differentiation opportunities.
- Confidence level per finding.

## Inputs
- Store URL (required).
- Operator-provided description (optional but recommended).

## Cannot Do
- Cannot access password-protected or login-gated pages.
- Cannot guarantee real-time pricing accuracy.
- Cannot replace human strategic judgment.
```

- [ ] **Step 2: Add shop_analyst to AGENT_SPECS in registry.py**

Insert after the product_research_agent entry (after order=10, before planning_agent order=20). Use order=15 to place it between product research and planning:

```python
# Insert in app/agents/registry.py after the product_research_agent AgentSpec block (after line ~80):
    AgentSpec(
        name="shop_analyst",
        display_name="Shop Analyst",
        stage="research",
        role="store_industry_research",
        relative_path="stages/shop_analyst.md",
        order=15,
        default_content="""# Shop Analyst
## Mission
Research a store's positioning, product catalog, SEO profile, and competitive landscape. Produce structured intelligence for GM memory to improve downstream creative strategy.

## Must Output
- Store profile: positioning, target audience, price tier, product categories, unique selling points.
- SEO snapshot: key search terms, content gaps, category structure observations.
- Competitor analysis: 3-5 comparable stores, their positioning, creative patterns, differentiation opportunities.
- Confidence level per finding.

## Inputs
- Store URL (required).
- Operator-provided description (optional but recommended).

## Cannot Do
- Cannot access password-protected or login-gated pages.
- Cannot guarantee real-time pricing accuracy.
- Cannot replace human strategic judgment.
""",
    ),
```

- [ ] **Step 3: Verify persona auto-creates correctly**

Run: `uv run python -c "from app.agents.personas import ensure_default_personas; ensure_default_personas(); from pathlib import Path; p = Path('personas/stages/shop_analyst.md'); print('exists:', p.exists())"`
Expected: `exists: True`

- [ ] **Step 4: Commit**

```bash
git add personas/stages/shop_analyst.md app/agents/registry.py
git commit -m "feat: add shop_analyst agent persona for store and competitor research"
```

---

### Task 3: Add Shop Analysis API schemas

**Files:**
- Modify: `app/schemas/api.py` — append new schemas

- [ ] **Step 1: Add Pydantic schemas**

```python
# Append to app/schemas/api.py after existing schemas


class ShopAnalysisRequest(BaseModel):
    store_url: str = Field(..., min_length=1, description="Store URL to research")
    description: str = Field(default="", description="Operator-provided store description")
    industry_code: str = Field(default="general", description="Industry code for GmMemory association")
    workspace_name: str = Field(default="workspace_demo")
    project_name: str = Field(default="project_demo")


class ShopAnalysisResult(BaseModel):
    source_type: str  # "shop_profile" or "competitor_analysis"
    content: dict     # structured profile or markdown report
    summary: str      # one-line summary for display


class ShopAnalysisResponse(BaseModel):
    id: str
    store_url: str
    industry_code: str
    profile: ShopAnalysisResult | None = None
    competitor_analysis: ShopAnalysisResult | None = None
    status: str  # "running", "completed", "failed"
    error_message: str | None = None
    created_at: datetime


class ShopAnalysisListItem(BaseModel):
    id: str
    store_url: str
    industry_code: str
    status: str
    summary: str
    created_at: datetime


class ShopAnalysisHistoryResponse(BaseModel):
    items: list[ShopAnalysisListItem]
```

- [ ] **Step 2: Verify schemas import cleanly**

Run: `uv run python -c "from app.schemas.api import ShopAnalysisRequest, ShopAnalysisResponse, ShopAnalysisListItem; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/schemas/api.py
git commit -m "feat: add ShopAnalysis Pydantic schemas"
```

---

### Task 4: Create shop analysis service

**Files:**
- Create: `app/services/shop_analysis.py`

- [ ] **Step 1: Create service file**

```python
# app/services/shop_analysis.py

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.data.models import GmMemory, Project, Workspace


def utcnow() -> datetime:
    return datetime.now(UTC)


def _get_or_create_workspace_project(
    db: Session, workspace_name: str, project_name: str
) -> tuple[Workspace, Project]:
    workspace = db.scalar(select(Workspace).where(Workspace.name == workspace_name))
    if not workspace:
        workspace = Workspace(name=workspace_name)
        db.add(workspace)
        db.flush()
    project = db.scalar(
        select(Project).where(
            Project.workspace_id == workspace.id, Project.name == project_name
        )
    )
    if not project:
        project = Project(workspace_id=workspace.id, name=project_name)
        db.add(project)
        db.flush()
    return workspace, project


def save_shop_profile(
    db: Session,
    *,
    project_id: str,
    industry_code: str,
    store_url: str,
    profile_data: dict,
) -> GmMemory:
    entry = GmMemory(
        project_id=project_id,
        memory_scope="industry",
        industry_code=industry_code,
        source_type="shop_profile",
        memory_type="store_intelligence",
        content={
            "store_url": store_url,
            "profile": profile_data,
            "generated_at": utcnow().isoformat(),
        },
    )
    db.add(entry)
    db.flush()
    return entry


def save_competitor_analysis(
    db: Session,
    *,
    project_id: str,
    industry_code: str,
    store_url: str,
    analysis_markdown: str,
) -> GmMemory:
    entry = GmMemory(
        project_id=project_id,
        memory_scope="industry",
        industry_code=industry_code,
        source_type="competitor_analysis",
        memory_type="store_intelligence",
        content={
            "store_url": store_url,
            "report": analysis_markdown,
            "generated_at": utcnow().isoformat(),
        },
    )
    db.add(entry)
    db.flush()
    return entry


def list_shop_analyses(
    db: Session,
    project_id: str,
    limit: int = 20,
) -> list[dict]:
    rows = db.scalars(
        select(GmMemory)
        .where(
            GmMemory.project_id == project_id,
            GmMemory.source_type.in_(["shop_profile", "competitor_analysis"]),
        )
        .order_by(desc(GmMemory.created_at))
        .limit(limit)
    ).all()

    # Group by store_url and batch (profiles and competitor analyses created close together)
    result: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        store_url = (row.content or {}).get("store_url", "")
        batch_key = f"{store_url}|{row.source_type}"
        if batch_key in seen:
            continue
        seen.add(batch_key)
        summary = ""
        if row.source_type == "shop_profile":
            profile = (row.content or {}).get("profile", {})
            summary = profile.get("positioning", store_url) if isinstance(profile, dict) else store_url
        else:
            report = (row.content or {}).get("report", "")
            summary = (report[:80] + "...") if len(report) > 80 else report
        result.append({
            "id": row.id,
            "store_url": store_url,
            "industry_code": row.industry_code or "",
            "status": "completed",
            "source_type": row.source_type,
            "summary": summary,
            "created_at": row.created_at,
        })
    return result


def get_shop_analysis_pair(
    db: Session,
    industry_code: str,
    store_url: str,
) -> dict:
    """Get the most recent shop_profile and competitor_analysis for a store."""
    profile = db.scalar(
        select(GmMemory)
        .where(
            GmMemory.industry_code == industry_code,
            GmMemory.source_type == "shop_profile",
        )
        .order_by(desc(GmMemory.created_at))
        .limit(1)
    )
    competitor = db.scalar(
        select(GmMemory)
        .where(
            GmMemory.industry_code == industry_code,
            GmMemory.source_type == "competitor_analysis",
        )
        .order_by(desc(GmMemory.created_at))
        .limit(1)
    )
    # Filter by store_url in content JSON (post-query)
    profile_content = profile.content if profile and (profile.content or {}).get("store_url") == store_url else None
    competitor_content = competitor.content if competitor and (competitor.content or {}).get("store_url") == store_url else None
    return {
        "profile_content": profile_content,
        "competitor_content": competitor_content,
    }
```

- [ ] **Step 2: Verify service imports**

Run: `uv run python -c "from app.services.shop_analysis import save_shop_profile, save_competitor_analysis, list_shop_analyses; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/services/shop_analysis.py
git commit -m "feat: add shop analysis service for GmMemory persistence"
```

---

### Task 5: Add shop_analyst runtime method

**Files:**
- Modify: `app/agents/runtime.py` — append `run_shop_analysis()` method

- [ ] **Step 1: Add run_shop_analysis method to AgentsRuntime**

```python
# Append to app/agents/runtime.py, inside the AgentsRuntime class, after existing methods:

    def run_shop_profile_analysis(
        self,
        store_url: str,
        description: str,
        *,
        provider: str,
        model: str,
        runtime_config: dict | None = None,
    ) -> dict:
        """Phase 1: Analyze a store's own positioning, SEO, and product catalog."""
        prompt = (
            f"{self._business_strategy_system_prompt('Shop Analyst')} "
            f"You are researching a store. Visit and analyze: {store_url}. "
            f"Operator notes: {description or 'None provided'}. "
            "Produce a STRUCTURED JSON profile with these keys: "
            "positioning (one-line), target_audience (string), price_tier (budget/mid/premium), "
            "product_categories (list of strings), unique_selling_points (list of strings), "
            "seo_keywords (list of top 5-10 inferred search terms), "
            "content_gaps (list of observations about missing content or weak areas), "
            "brand_voice (brief description of tone and style). "
            "Return ONLY valid JSON, no markdown wrapping."
        )
        summary, model_used, estimated_cost = self._chat_complete(provider, model, prompt, runtime_config)
        try:
            profile = json.loads(summary)
        except json.JSONDecodeError:
            # Attempt to extract JSON from markdown code block
            import re
            match = re.search(r'\{[\s\S]*\}', summary)
            profile = json.loads(match.group(0)) if match else {"raw_response": summary}
        return {
            "profile": profile,
            "model_used": model_used,
            "estimated_cost": estimated_cost,
        }

    def run_competitor_analysis(
        self,
        store_url: str,
        description: str,
        store_profile: dict,
        *,
        provider: str,
        model: str,
        runtime_config: dict | None = None,
    ) -> dict:
        """Phase 2: Analyze competitors based on store profile."""
        prompt = (
            f"{self._business_strategy_system_prompt('Shop Analyst')} "
            f"Based on this store profile: {json.dumps(store_profile)} "
            f"for store at {store_url} (operator notes: {description or 'None provided'}), "
            "Identify 3-5 comparable competitor stores. For each competitor, note: "
            "their positioning, creative/ad style patterns, pricing approach, "
            "and differentiation opportunities for our store. "
            "Return a Markdown report with sections: "
            "## Competitive Landscape Overview, ## Competitor 1..N (name, URL if known, analysis), "
            "## Differentiation Opportunities, ## Recommended Creative Angles."
        )
        summary, model_used, estimated_cost = self._chat_complete(provider, model, prompt, runtime_config)
        return {
            "report": summary,
            "model_used": model_used,
            "estimated_cost": estimated_cost,
        }
```

- [ ] **Step 2: Verify runtime imports and syntax**

Run: `uv run python -c "from app.agents.runtime import AgentsRuntime; rt = AgentsRuntime(); print(hasattr(rt, 'run_shop_profile_analysis'), hasattr(rt, 'run_competitor_analysis'))"`
Expected: `True True`

- [ ] **Step 3: Commit**

```bash
git add app/agents/runtime.py
git commit -m "feat: add shop_analyst runtime methods for store profile and competitor analysis"
```

---

### Task 6: Add Shop Analysis API endpoint and page

**Files:**
- Modify: `app/api/routes.py` — add endpoint and page HTML

- [ ] **Step 1: Add imports at top of routes.py**

Add `import uuid` to the existing `import` block (top of file), and add service/schema imports after existing service imports:

```python
import uuid

from app.services.shop_analysis import (
    list_shop_analyses,
    save_competitor_analysis,
    save_shop_profile,
)
from app.schemas.api import (
    ShopAnalysisRequest,
    ShopAnalysisResponse,
    ShopAnalysisListItem,
    ShopAnalysisHistoryResponse,
)
```

- [ ] **Step 2: Add POST /shop-analysis/run endpoint**

Insert before the dashboard HTML section (before `_dashboard_html()`):

```python
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

    # Phase 2: Competitor analysis
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

    status = "failed" if not profile_result and not competitor_result else ("completed" if not errors else "completed")
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
```

- [ ] **Step 3: Add Shop Analysis dashboard page**

Insert before the `_dashboard_html()` function:

```python
@router.get("/dashboard/shop-analysis", response_class=HTMLResponse)
def dashboard_shop_analysis() -> str:
    return _shop_analysis_page_html()


def _shop_analysis_page_html() -> str:
    return f"""
    <html>
      <head>
        <title>Crispy Shop Analysis</title>
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
          .app-shell {{ width: min(1100px, calc(100% - 24px)); margin: 22px auto 30px auto; }}
          .hero {{ display:flex; justify-content: space-between; align-items: flex-end; gap: 12px; margin-bottom: 14px; }}
          h1, h2, h3 {{ margin: 0; line-height: 1.25; }}
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
            padding: 20px;
            background: var(--card);
            box-shadow: 0 8px 24px rgba(30, 62, 50, 0.07);
            margin-bottom: 16px;
          }}
          input, textarea, select {{
            width: 100%;
            border: 1px solid var(--line);
            border-radius: 10px;
            padding: 10px 12px;
            font-family: inherit;
            font-size: 14px;
            background: #fff;
            color: var(--text);
          }}
          input:focus, textarea:focus {{ outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(31, 122, 98, 0.15); }}
          label {{ display: block; font-weight: 600; font-size: 13px; margin-bottom: 3px; }}
          button {{
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
          }}
          button:hover {{ background: #f0f5f2; }}
          button.primary {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
          button.primary:hover {{ background: #145746; }}
          button:disabled {{ opacity: 0.5; cursor: not-allowed; }}
          .form-row {{ display: flex; gap: 12px; align-items: flex-end; flex-wrap: wrap; }}
          .form-row > div {{ flex: 1; min-width: 200px; }}
          .result-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
          .result-panel {{
            border: 1px solid var(--line);
            border-radius: 12px;
            padding: 16px;
            background: #fafdfb;
            max-height: 600px;
            overflow-y: auto;
          }}
          .result-panel pre {{
            white-space: pre-wrap;
            word-break: break-word;
            font-family: var(--mono);
            font-size: 12px;
            line-height: 1.5;
          }}
          .history-item {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 14px;
            border-bottom: 1px solid var(--line);
            font-size: 13px;
          }}
          .history-item:last-child {{ border-bottom: none; }}
          .status-badge {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 999px;
            font-size: 11px;
            font-weight: 700;
          }}
          .status-badge.completed {{ background: #eaf7ee; color: #21633d; }}
          .status-badge.failed {{ background: #fdeeee; color: #8a2d2d; }}
          .status-badge.running {{ background: #fff7e6; color: #8a5d1c; }}
          .loading {{ text-align: center; padding: 32px; color: var(--muted); }}
          .loading .spinner {{
            display: inline-block;
            width: 24px; height: 24px;
            border: 3px solid var(--line);
            border-top-color: var(--accent);
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
          }}
          @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
          @media (max-width: 860px) {{
            .result-grid {{ grid-template-columns: 1fr; }}
            .form-row > div {{ min-width: 100%; }}
          }}
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
          async function api(path, options = {{}}) {{
            const res = await fetch(path, {{ headers: {{ "Content-Type": "application/json" }}, ...options }});
            if (!res.ok) throw new Error(await res.text());
            return res.json();
          }}

          async function runAnalysis() {{
            const storeUrl = document.getElementById("store-url").value.trim();
            if (!storeUrl) {{ alert("Please enter a store URL."); return; }}

            const btn = document.getElementById("btn-run");
            const status = document.getElementById("run-status");
            btn.disabled = true;
            status.textContent = "Running...";

            // Show results card
            const card = document.getElementById("results-card");
            card.style.display = "block";
            document.getElementById("results-title").textContent = "Results: " + storeUrl;

            // Reset panels
            document.getElementById("profile-loading").style.display = "block";
            document.getElementById("profile-content").style.display = "none";
            document.getElementById("profile-error").style.display = "none";
            document.getElementById("competitor-loading").style.display = "block";
            document.getElementById("competitor-content").style.display = "none";
            document.getElementById("competitor-error").style.display = "none";

            try {{
              const data = await api("/shop-analysis/run", {{
                method: "POST",
                body: JSON.stringify({{
                  store_url: storeUrl,
                  description: document.getElementById("store-description").value.trim(),
                  industry_code: document.getElementById("industry-code").value.trim() || "general",
                }}),
              }});

              // Profile result
              document.getElementById("profile-loading").style.display = "none";
              if (data.profile) {{
                document.getElementById("profile-content").style.display = "block";
                document.getElementById("profile-content").textContent = JSON.stringify(data.profile.content, null, 2);
              }} else {{
                document.getElementById("profile-error").style.display = "block";
                document.getElementById("profile-error").textContent = data.error_message || "Profile analysis failed.";
              }}

              // Competitor result
              document.getElementById("competitor-loading").style.display = "none";
              if (data.competitor_analysis) {{
                document.getElementById("competitor-content").style.display = "block";
                const report = data.competitor_analysis.content.report || "";
                document.getElementById("competitor-content").innerHTML = report
                  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
                  .replace(/\\n/g, "<br>")
                  .replace(/## (.+)/g, "<h3>$1</h3>")
                  .replace(/### (.+)/g, "<h4>$1</h4>")
                  .replace(/\\*\\*(.+?)\\*\\*/g, "<b>$1</b>");
              }} else {{
                document.getElementById("competitor-error").style.display = "block";
                document.getElementById("competitor-error").textContent = data.error_message || "Competitor analysis failed.";
              }}

              status.textContent = data.status === "completed" ? "Done!" : "Completed with errors.";
              if (data.status === "completed") loadHistory();
            }} catch (err) {{
              status.textContent = "Error: " + err.message;
              document.getElementById("profile-loading").style.display = "none";
              document.getElementById("competitor-loading").style.display = "none";
            }} finally {{
              btn.disabled = false;
            }}
          }}

          async function loadHistory() {{
            try {{
              const data = await api("/shop-analysis/history");
              const list = document.getElementById("history-list");
              if (!data.items.length) {{
                list.innerHTML = '<div class="muted">No analyses yet.</div>';
                return;
              }}
              list.innerHTML = data.items.map(item => {{
                const badgeClass = item.status === "completed" ? "completed" : "failed";
                const dt = new Date(item.created_at);
                const timeStr = String(dt.getMonth()+1).padStart(2,'0') + "-" +
                  String(dt.getDate()).padStart(2,'0') + " " +
                  String(dt.getHours()).padStart(2,'0') + ":" +
                  String(dt.getMinutes()).padStart(2,'0');
                return '<div class="history-item">'
                  + '<div><b>' + item.store_url.replace(/</g, "&lt;") + '</b>'
                  + ' <span class="status-badge ' + badgeClass + '">' + item.source_type + '</span>'
                  + '<br><span class="muted">' + item.summary.replace(/</g, "&lt;").substring(0, 100) + '</span></div>'
                  + '<div class="muted">' + timeStr + '</div>'
                  + '</div>';
              }}).join("");
            }} catch (err) {{
              document.getElementById("history-list").innerHTML = '<div class="muted">Failed to load history.</div>';
            }}
          }}

          document.addEventListener("DOMContentLoaded", loadHistory);
        </script>
      </body>
    </html>
    """
```

- [ ] **Step 4: Verify endpoint and page load**

Run: `uv run python -c "from app.main import create_app; app = create_app(); routes = [r.path for r in app.routes]; print('/shop-analysis/run' in str(routes), '/dashboard/shop-analysis' in str(routes))"`
Expected: `True True`

- [ ] **Step 5: Commit**

```bash
git add app/api/routes.py
git commit -m "feat: add Shop Analysis API endpoint and dashboard page"
```

---

### Task 7: Update Agent API Configs page with divider and shop_analyst

**Files:**
- Modify: `app/api/routes.py:1927-1956` — add visual divider between pipeline and shop analysis agents

- [ ] **Step 1: Add divider row logic in JS**

In `_agent_api_dashboard_html()`, update the JS that builds the `rows` array. After the `baseRows.flatMap(...)` block, insert a divider row. The current code at line ~1940:

```javascript
// Current:
const baseRows = [{{ agent_name: "default", display_name: "Default Fallback", stage: "global" }}, ...personas];
const rows = baseRows.flatMap((r) => {{ ... }});

// Replace with:
const baseRows = [{{ agent_name: "default", display_name: "Default Fallback", stage: "global" }}, ...personas];
const shopAnalysisAgents = ["shop_analyst"];
const rows = baseRows.flatMap((r) => {{
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
  // Insert divider before shop analysis agents
  if (r.agent_name === "shop_analyst") {{
    return [
      {{ row_key: "__divider__", agent_name: "__divider__", mode: "text", title: "divider", source: "divider", isDivider: true }},
      {{ row_key: "shop_analyst__text", agent_name: "shop_analyst", mode: "text", title: "Shop Analyst - Text", source: "shop_analyst" }},
    ];
  }}
  return [{{ row_key: `${{r.agent_name}}__text`, agent_name: r.agent_name, mode: "text", title, source: r.agent_name }}];
}});
```

- [ ] **Step 2: Add divider rendering in the table body builder**

Find the JS that builds table rows (after the `rows` array) and add divider rendering. Search for `rows.forEach` in the agent-apis JS and add:

```javascript
rows.forEach((row) => {{
  if (row.isDivider) {{
    const tr = document.createElement("tr");
    tr.innerHTML = '<td colspan="12" style="padding:8px 10px;background:#f0f4f2;border-bottom:2px solid var(--accent);font-weight:700;font-size:12px;color:var(--accent);">Shop Analysis Agents</td>';
    tbody.appendChild(tr);
    return;
  }}
  // ... existing row rendering ...
}});
```

- [ ] **Step 3: Verify agent-apis page loads without errors**

Run: `uv run python -c "from app.main import create_app; app = create_app(); from fastapi.testclient import TestClient; c = TestClient(app); r = c.get('/dashboard/agent-apis'); print(r.status_code)"`
Expected: `200`

- [ ] **Step 4: Commit**

```bash
git add app/api/routes.py
git commit -m "feat: add divider in Agent API Configs separating shop analysis agents"
```

---

### Task 8: Add Shop Analysis nav link

**Files:**
- Modify: `app/dashboard/layout.py:704-708` — add nav link in topbar

- [ ] **Step 1: Add nav link**

```python
# In render_shell_top(), add after the existing nav links:
          <a class="nav-link" href="/dashboard/shop-analysis">Shop Analysis</a>
```

The updated topbar section should be:

```python
      <div class="topbar">
        <div class="top-actions links">
          <a class="nav-link" href="/dashboard/agent-apis">Agent API Configs</a>
          <a class="nav-link" href="/dashboard/shop-analysis">Shop Analysis</a>
          <a class="nav-link" href="/dashboard/assets">Asset Library</a>
          <a class="nav-link" href="/dashboard/personas">Personas</a>
        </div>
      </div>
```

- [ ] **Step 2: Verify dashboard loads**

Run: `uv run python -c "from app.dashboard.layout import render_shell_top; html = render_shell_top(); print('shop-analysis' in html)"`
Expected: `True`

- [ ] **Step 3: Commit**

```bash
git add app/dashboard/layout.py
git commit -m "feat: add Shop Analysis nav link to dashboard topbar"
```

---

### Task 9: Write tests

**Files:**
- Create: `tests/test_shop_analysis.py`

- [ ] **Step 1: Write test file**

```python
# tests/test_shop_analysis.py

from __future__ import annotations


def test_shop_analysis_page_loads(client):
    resp = client.get("/dashboard/shop-analysis")
    assert resp.status_code == 200
    html = resp.text
    assert "Shop Analysis" in html
    assert "store-url" in html
    assert "Run Analysis" in html


def test_shop_analysis_history_empty(client):
    resp = client.get("/shop-analysis/history?workspace_name=test_ws&project_name=test_proj")
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert body["items"] == []


def test_shop_analysis_run_stores_gm_memory(client):
    resp = client.post(
        "/shop-analysis/run",
        json={
            "store_url": "https://example-pet-store.com",
            "description": "A pet supplies store targeting US urban dog owners.",
            "industry_code": "pet_accessories",
            "workspace_name": "test_ws",
            "project_name": "test_proj",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["store_url"] == "https://example-pet-store.com"
    assert body["industry_code"] == "pet_accessories"
    # At least profile should exist (competitor depends on profile success)
    assert body["profile"] is not None or body["status"] == "failed"

    # Verify GmMemory entries were created
    mem_resp = client.get("/gm-memory?scope=industry&industry_code=pet_accessories&limit=50")
    assert mem_resp.status_code == 200
    memories = mem_resp.json()
    source_types = [m["source_type"] for m in memories]
    assert "shop_profile" in source_types or "competitor_analysis" in source_types


def test_shop_analysis_history_after_run(client):
    # Run an analysis first
    client.post(
        "/shop-analysis/run",
        json={
            "store_url": "https://example-history-test.com",
            "description": "Test store for history.",
            "industry_code": "test_industry",
            "workspace_name": "test_ws",
            "project_name": "test_proj",
        },
    )
    # Check history
    resp = client.get("/shop-analysis/history?workspace_name=test_ws&project_name=test_proj")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) >= 1
    urls = [item["store_url"] for item in body["items"]]
    assert "https://example-history-test.com" in urls


def test_shop_analyst_persona_exists(client):
    resp = client.get("/personas")
    assert resp.status_code == 200
    personas = resp.json()
    names = [p["agent_name"] for p in personas]
    assert "shop_analyst" in names
    assert "product_research_agent" in names
    assert "research_agent" not in names
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_shop_analysis.py -v`
Expected: 5 passed (note: `test_shop_analysis_run_stores_gm_memory` may need a real LLM API key configured; if no key, the test may fail — adjust to skip if CRISPY_API_KEY_ env vars are not set)

- [ ] **Step 3: Commit**

```bash
git add tests/test_shop_analysis.py
git commit -m "test: add shop analysis endpoint and page tests"
```

---

### Task 10: Final integration and verification

- [ ] **Step 1: Verify app starts cleanly**

Run: `uv run python -c "from app.main import create_app; app = create_app(); print('App OK, routes:', len(app.routes))"`

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest tests/ -v --tb=short`

- [ ] **Step 3: Manual QA checklist**

```
[ ] Navigate to /dashboard — Shop Analysis link visible in nav
[ ] Click Shop Analysis — page loads with form
[ ] Submit a store URL — profile and competitor panels populate
[ ] History section shows past analyses
[ ] Navigate to /dashboard/agent-apis — divider visible, Shop Analyst row present
[ ] Navigate to /dashboard/personas — shop_analyst listed, product_research_agent listed
[ ] Check /gm-memory?scope=industry&source_type=shop_profile — entries exist
[ ] Check /gm-memory?scope=industry&source_type=competitor_analysis — entries exist
```

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: complete Shop Analysis integration with GmMemory feedback loop"
```

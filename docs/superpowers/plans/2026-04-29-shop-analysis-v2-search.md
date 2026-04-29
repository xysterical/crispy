# Shop Analysis v2: Tavily + Firecrawl Search Integration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace placeholder prompt-based shop analysis with real web search via Tavily (semantic search) and Firecrawl (page scraping), integrated through the `shop_analyst` agent's API config.

**Architecture:** New `app/search/` module with lightweight Tavily and Firecrawl SDK wrappers. `shop_analyst` runtime methods rewritten to call search tools, inject results into LLM prompts, and produce structured profiles. Agent API Configs page splits shop_analyst into three rows (LLM / Tavily / Firecrawl) following the existing generation_agent multi-row pattern. API keys stored as env var names in `AgentApiConfig.extra`, real keys in environment variables.

**Tech Stack:** Python 3.11+, `tavily-python`, `firecrawl-py`, FastAPI, SQLAlchemy 2.0, raw HTML/CSS/JS, pytest

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `pyproject.toml` | Modify | Add `tavily-python`, `firecrawl-py` dependencies |
| `app/search/__init__.py` | Create | Module init |
| `app/search/tavily_client.py` | Create | Tavily Search API wrapper |
| `app/search/firecrawl_client.py` | Create | Firecrawl Scrape API wrapper |
| `app/agents/runtime.py` | Modify | Rewrite `run_shop_profile_analysis()` and `run_competitor_analysis()` |
| `app/api/routes.py` | Modify | Update `_serialize_agent_config()`, JS rows, and `POST /shop-analysis/run` |
| `app/schemas/api.py` | Modify | Add tavily/firecrawl key fields to AgentApiConfigView |
| `tests/test_shop_analysis.py` | Modify | Add search integration tests |

---

### Task 1: Add dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add tavily-python and firecrawl-py**

```bash
uv add tavily-python firecrawl-py
```

- [ ] **Step 2: Verify imports work**

```bash
uv run python -c "import tavily; import firecrawl; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add tavily-python and firecrawl-py for web search integration"
```

---

### Task 2: Create Tavily search client

**Files:**
- Create: `app/search/__init__.py`
- Create: `app/search/tavily_client.py`

- [ ] **Step 1: Create module init**

```python
# app/search/__init__.py
from __future__ import annotations

from app.search.tavily_client import TavilyClient
from app.search.firecrawl_client import FirecrawlClient

__all__ = ["TavilyClient", "FirecrawlClient"]
```

- [ ] **Step 2: Create Tavily client**

```python
# app/search/tavily_client.py
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class TavilySearchResult:
    title: str
    url: str
    content: str
    score: float = 0.0


@dataclass(slots=True)
class TavilySearchResponse:
    query: str
    results: list[TavilySearchResult] = field(default_factory=list)
    answer: str = ""


class TavilyClient:
    """Lightweight wrapper around Tavily Search API for AI agent use."""

    def __init__(self, api_key: str) -> None:
        from tavily import TavilyClient as _TavilyClient
        self._client = _TavilyClient(api_key=api_key)

    def search(self, query: str, *, max_results: int = 5, include_answer: bool = True) -> TavilySearchResponse:
        """Execute a semantic search query. Returns structured results with content snippets."""
        response = self._client.search(
            query=query,
            max_results=max_results,
            include_answer=include_answer,
            search_depth="basic",
        )
        results = [
            TavilySearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                content=r.get("content", ""),
                score=float(r.get("score", 0)),
            )
            for r in (response.get("results") or [])
        ]
        return TavilySearchResponse(
            query=response.get("query", query),
            results=results,
            answer=response.get("answer", ""),
        )

    def search_raw(self, query: str, *, max_results: int = 5) -> dict:
        """Return raw Tavily response dict for advanced use cases."""
        return self._client.search(query=query, max_results=max_results, search_depth="basic")
```

- [ ] **Step 3: Verify import**

```bash
uv run python -c "from app.search import TavilyClient; print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app/search/__init__.py app/search/tavily_client.py
git commit -m "feat: add Tavily search client wrapper"
```

---

### Task 3: Create Firecrawl scrape client

**Files:**
- Create: `app/search/firecrawl_client.py`

- [ ] **Step 1: Create Firecrawl client**

```python
# app/search/firecrawl_client.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class FirecrawlScrapeResult:
    title: str
    url: str
    markdown: str
    metadata: dict


class FirecrawlClient:
    """Lightweight wrapper around Firecrawl Scrape API for AI agent use."""

    def __init__(self, api_key: str) -> None:
        from firecrawl import FirecrawlApp
        self._app = FirecrawlApp(api_key=api_key)

    def scrape(self, url: str) -> FirecrawlScrapeResult:
        """Scrape a single URL and return cleaned markdown content."""
        response = self._app.scrape_url(url, params={"formats": ["markdown"]})
        if not isinstance(response, dict):
            raise RuntimeError(f"Firecrawl scrape failed for {url}: unexpected response type")
        return FirecrawlScrapeResult(
            title=response.get("title", ""),
            url=url,
            markdown=response.get("markdown", "") or "",
            metadata=response.get("metadata", {}),
        )

    def scrape_raw(self, url: str) -> dict:
        """Return raw Firecrawl scrape response dict."""
        response = self._app.scrape_url(url, params={"formats": ["markdown"]})
        if not isinstance(response, dict):
            raise RuntimeError(f"Firecrawl scrape failed for {url}")
        return response
```

- [ ] **Step 2: Verify import**

```bash
uv run python -c "from app.search import FirecrawlClient; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/search/firecrawl_client.py
git commit -m "feat: add Firecrawl scrape client wrapper"
```

---

### Task 4: Rewrite runtime methods to use search tools

**Files:**
- Modify: `app/agents/runtime.py:1733-1794`

- [ ] **Step 1: Replace run_shop_profile_analysis**

Replace the existing method (lines 1733-1765) with:

```python
    def run_shop_profile_analysis(
        self,
        store_url: str,
        description: str,
        *,
        provider: str,
        model: str,
        runtime_config: dict | None = None,
        tavily_api_key: str | None = None,
        firecrawl_api_key: str | None = None,
    ) -> dict:
        """Phase 1: Analyze a store's own positioning, SEO, and product catalog using real web search."""
        from app.search import FirecrawlClient, TavilyClient

        # Gather real data from the store
        store_content = ""
        tavily_results: dict = {}
        search_errors: list[str] = []

        if firecrawl_api_key:
            try:
                fc = FirecrawlClient(api_key=firecrawl_api_key)
                result = fc.scrape(store_url)
                store_content = result.markdown[:8000]  # Truncate for prompt budget
            except Exception as exc:
                search_errors.append(f"firecrawl_scrape: {exc}")

        if tavily_api_key:
            try:
                tv = TavilyClient(api_key=tavily_api_key)
                # Search for brand info based on description or store URL domain
                search_query = f"{description or store_url} brand positioning reviews target audience"
                tavily_results = tv.search_raw(search_query, max_results=5)
            except Exception as exc:
                search_errors.append(f"tavily_search: {exc}")

        # Build prompt with real data injected
        prompt_parts = [
            f"{self._business_strategy_system_prompt('Shop Analyst')}",
            f"Research this store: {store_url}",
            f"Operator description: {description or 'None provided'}.",
        ]
        if store_content:
            prompt_parts.append(
                f"SCRAPED STORE CONTENT (from Firecrawl):\n{store_content}\n---"
            )
        if tavily_results:
            prompt_parts.append(
                f"WEB SEARCH RESULTS (from Tavily): {json.dumps(tavily_results, indent=2)}\n---"
            )
        if search_errors:
            prompt_parts.append(
                f"Search errors (partial data): {'; '.join(search_errors)}"
            )
        prompt_parts.append(
            "Produce a STRUCTURED JSON profile: positioning (one-line), target_audience (string), "
            "price_tier (budget/mid/premium), product_categories (list), unique_selling_points (list), "
            "seo_keywords (list of 5-10 search terms), content_gaps (list), "
            "brand_voice (tone and style description). "
            "Return ONLY valid JSON, no markdown wrapping."
        )
        prompt = "\n".join(prompt_parts)

        summary, model_used, estimated_cost = self._chat_complete(provider, model, prompt, runtime_config)
        try:
            profile = json.loads(summary)
        except json.JSONDecodeError:
            match = re.search(r'\{[\s\S]*\}', summary)
            profile = json.loads(match.group(0)) if match else {"raw_response": summary}

        return {
            "profile": profile,
            "model_used": model_used,
            "estimated_cost": estimated_cost,
            "search_errors": search_errors if search_errors else None,
        }
```

- [ ] **Step 2: Replace run_competitor_analysis**

Replace the existing method (lines 1767-1794) with:

```python
    def run_competitor_analysis(
        self,
        store_url: str,
        description: str,
        store_profile: dict,
        *,
        provider: str,
        model: str,
        runtime_config: dict | None = None,
        tavily_api_key: str | None = None,
        firecrawl_api_key: str | None = None,
    ) -> dict:
        """Phase 2: Analyze competitors based on store profile using real web search."""
        from app.search import FirecrawlClient, TavilyClient

        search_errors: list[str] = []
        competitor_search_results: dict = {}
        competitor_pages: list[str] = []

        if tavily_api_key:
            try:
                tv = TavilyClient(api_key=tavily_api_key)
                # Build search query from store profile
                positioning = store_profile.get("positioning", description)
                categories = store_profile.get("product_categories", [])
                cat_str = ", ".join(categories[:3]) if categories else ""
                query = f"competitors similar to {positioning} {cat_str} online store"
                competitor_search_results = tv.search_raw(query, max_results=5)

                # Collect competitor URLs to scrape
                for r in (competitor_search_results.get("results") or []):
                    url = r.get("url", "")
                    if url and url != store_url:
                        competitor_pages.append(url)
            except Exception as exc:
                search_errors.append(f"tavily_competitor_search: {exc}")

        # Scrape up to 3 competitor pages
        competitor_content: list[str] = []
        if firecrawl_api_key and competitor_pages:
            try:
                fc = FirecrawlClient(api_key=firecrawl_api_key)
                for comp_url in competitor_pages[:3]:
                    try:
                        result = fc.scrape(comp_url)
                        competitor_content.append(
                            f"URL: {comp_url}\nTITLE: {result.title}\n{result.markdown[:4000]}"
                        )
                    except Exception:
                        competitor_content.append(f"URL: {comp_url}\n[Scrape failed]")
            except Exception as exc:
                search_errors.append(f"firecrawl_competitor: {exc}")

        # Build prompt
        prompt_parts = [
            f"{self._business_strategy_system_prompt('Shop Analyst')}",
            f"Store profile: {json.dumps(store_profile)}",
            f"Store URL: {store_url}",
            f"Operator notes: {description or 'None provided'}.",
        ]
        if competitor_search_results:
            prompt_parts.append(
                f"COMPETITOR SEARCH RESULTS: {json.dumps(competitor_search_results, indent=2)}\n---"
            )
        if competitor_content:
            prompt_parts.append(
                "COMPETITOR PAGE CONTENT:\n" + "\n---\n".join(competitor_content)
            )
        if search_errors:
            prompt_parts.append(f"Search errors (partial data): {'; '.join(search_errors)}")
        prompt_parts.append(
            "Identify 3-5 comparable competitors. For each: positioning, creative/ad style patterns, "
            "pricing approach, differentiation opportunities. "
            "Return Markdown with: ## Competitive Landscape Overview, ## Competitor N (name, URL, analysis), "
            "## Differentiation Opportunities, ## Recommended Creative Angles."
        )
        prompt = "\n".join(prompt_parts)

        summary, model_used, estimated_cost = self._chat_complete(provider, model, prompt, runtime_config)
        return {
            "report": summary,
            "model_used": model_used,
            "estimated_cost": estimated_cost,
            "search_errors": search_errors if search_errors else None,
        }
```

- [ ] **Step 3: Verify runtime methods exist and signature is correct**

```bash
uv run python -c "
from app.agents.runtime import AgentsRuntime
import inspect
rt = AgentsRuntime()
sig = inspect.signature(rt.run_shop_profile_analysis)
params = list(sig.parameters.keys())
print('tavily_api_key' in params, 'firecrawl_api_key' in params)
"
```
Expected: `True True`

- [ ] **Step 4: Commit**

```bash
git add app/agents/runtime.py
git commit -m "feat: rewrite shop_analyst runtime methods with Tavily + Firecrawl integration"
```

---

### Task 5: Update AgentApiConfigView and serialization for search key fields

**Files:**
- Modify: `app/schemas/api.py` — add fields to AgentApiConfigView
- Modify: `app/api/routes.py` — update `_serialize_agent_config()`

- [ ] **Step 1: Add fields to AgentApiConfigView**

Find `AgentApiConfigView` in `app/schemas/api.py` (search for `class AgentApiConfigView`). Add two new optional fields after the existing `video_api_key_available` line:

```python
    tavily_api_key_env: str | None = None
    tavily_api_key_available: bool = False
    firecrawl_api_key_env: str | None = None
    firecrawl_api_key_available: bool = False
```

- [ ] **Step 2: Update _serialize_agent_config in routes.py**

In `_serialize_agent_config()`, after the video config section, add:

```python
    # Search tool configs for shop_analyst
    extra = row.extra if isinstance(row.extra, dict) else {}
    tavily_cfg = extra.get("tavily_config") or {}
    firecrawl_cfg = extra.get("firecrawl_config") or {}
    tavily_key_env = tavily_cfg.get("api_key_env")
    firecrawl_key_env = firecrawl_cfg.get("api_key_env")
```

Then add to the return dict:

```python
        tavily_api_key_env=tavily_key_env,
        tavily_api_key_available=api_key_available(tavily_key_env),
        firecrawl_api_key_env=firecrawl_key_env,
        firecrawl_api_key_available=api_key_available(firecrawl_key_env),
```

- [ ] **Step 3: Verify schema imports**

```bash
uv run python -c "from app.schemas.api import AgentApiConfigView; import inspect; fields = list(AgentApiConfigView.model_fields.keys()); print('tavily_api_key_env' in fields, 'firecrawl_api_key_env' in fields)"
```
Expected: `True True`

- [ ] **Step 4: Commit**

```bash
git add app/schemas/api.py app/api/routes.py
git commit -m "feat: add Tavily and Firecrawl API key fields to AgentApiConfigView"
```

---

### Task 6: Update POST /shop-analysis/run to extract and pass search keys

**Files:**
- Modify: `app/api/routes.py` — in the `run_shop_analysis` endpoint (around line 2855)

- [ ] **Step 1: Extract search API keys from config extra**

In the `run_shop_analysis` function, after `runtime_config = resolve_agent_runtime(config)`, add:

```python
    # Extract search tool API keys from config extra
    extra = config.get("extra") or {}
    tavily_cfg = extra.get("tavily_config") or {}
    firecrawl_cfg = extra.get("firecrawl_config") or {}
    import os
    tavily_api_key = os.getenv(tavily_cfg.get("api_key_env", "")) if tavily_cfg.get("api_key_env") else None
    firecrawl_api_key = os.getenv(firecrawl_cfg.get("api_key_env", "")) if firecrawl_cfg.get("api_key_env") else None
```

- [ ] **Step 2: Pass keys to runtime methods**

Update the `run_shop_profile_analysis()` call to include the new params:

```python
        result = runtime.run_shop_profile_analysis(
            store_url=payload.store_url,
            description=payload.description,
            provider=provider,
            model=model,
            runtime_config=runtime_config,
            tavily_api_key=tavily_api_key,
            firecrawl_api_key=firecrawl_api_key,
        )
```

Update the `run_competitor_analysis()` call similarly:

```python
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
```

- [ ] **Step 3: Verify endpoint loads**

```bash
uv run python -c "from app.main import create_app; app = create_app(); print('/shop-analysis/run' in str([r.path for r in app.routes]))"
```
Expected: `True`

- [ ] **Step 4: Commit**

```bash
git add app/api/routes.py
git commit -m "feat: wire search API keys from AgentApiConfig into shop_analyst runtime calls"
```

---

### Task 7: Update Agent API Configs JS for three-row shop_analyst

**Files:**
- Modify: `app/api/routes.py` — in `_agent_api_dashboard_html()` JS (around line 2258)

- [ ] **Step 1: Expand shop_analyst flatMap to three rows**

Replace the current shop_analyst block in the `flatMap` callback:

```javascript
// Current (lines 2258-2262):
if (shopAnalysisAgents.has(r.agent_name)) {
  return [
    { row_key: "__divider_shop__", agent_name: "__divider__", mode: "text", title: "divider", source: "divider", isDivider: true },
    { row_key: `shop_analyst__text`, agent_name: "shop_analyst", mode: "text", title: "Shop Analyst - Text", source: "shop_analyst" },
  ];
}

// Replace with:
if (shopAnalysisAgents.has(r.agent_name)) {
  return [
    { row_key: "__divider_shop__", agent_name: "__divider__", mode: "text", title: "divider", source: "divider", isDivider: true },
    { row_key: "shop_analyst__text", agent_name: "shop_analyst", mode: "text", title: "Shop Analyst - LLM", source: "shop_analyst" },
    { row_key: "shop_analyst__tavily", agent_name: "shop_analyst", mode: "tavily", title: "Shop Analyst - Tavily", source: "shop_analyst" },
    { row_key: "shop_analyst__firecrawl", agent_name: "shop_analyst", mode: "firecrawl", title: "Shop Analyst - Firecrawl", source: "shop_analyst" },
  ];
}
```

- [ ] **Step 2: Add saving logic for tavily/firecrawl extra fields**

Find the `saveConfig` function in the JS and add logic to handle the tavily/firecrawl rows. When `row.mode === "tavily"`, store the env var in `extra.tavily_config.api_key_env`. When `row.mode === "firecrawl"`, store in `extra.firecrawl_config.api_key_env`. When `row.mode === "text"`, store the LLM config as usual.

Add to the saveConfig function, after the existing extra handling:

```javascript
// Build extra based on mode
const existing = byAgent[row.agent_name] || {};
let extra = { ...(existing.extra || {}) };
if (row.mode === "tavily") {
  extra.tavily_config = { api_key_env: apiKeyEnv.value };
} else if (row.mode === "firecrawl") {
  extra.firecrawl_config = { api_key_env: apiKeyEnv.value };
}
// For text mode, preserve existing tavily/firecrawl configs in extra
```

- [ ] **Step 3: Add cell rendering for tavily/firecrawl rows**

In the `render()` function's row loop, handle tavily and firecrawl modes. These rows should only show the API Key Env column and Env Status column as editable; Provider and Model columns should show "-" (N/A):

```javascript
const isSearchTool = (r.mode === "tavily" || r.mode === "firecrawl");
const providerCell = isSearchTool ? '<td class="muted">-</td>' : `<td>...</td>`;
const modelCell = isSearchTool ? '<td class="muted">-</td>' : `<td>...</td>`;
```

- [ ] **Step 4: Verify agent-apis page loads**

```bash
uv run python -c "from app.main import create_app; from fastapi.testclient import TestClient; c = TestClient(create_app()); r = c.get('/dashboard/agent-apis'); print(r.status_code, 'Shop Analyst - Tavily' in r.text, 'Shop Analyst - Firecrawl' in r.text)"
```
Expected: `200 True True`

- [ ] **Step 5: Commit**

```bash
git add app/api/routes.py
git commit -m "feat: expand shop_analyst to three rows in Agent API Configs (LLM/Tavily/Firecrawl)"
```

---

### Task 8: Write tests

**Files:**
- Modify: `tests/test_shop_analysis.py`

- [ ] **Step 1: Add search integration tests**

Append to `tests/test_shop_analysis.py`:

```python

def test_shop_analyst_config_has_search_key_fields(client):
    """Verify AgentApiConfigView includes tavily and firecrawl key fields."""
    resp = client.get("/agent-configs")
    assert resp.status_code == 200
    configs = resp.json()
    # Find the shop_analyst config or verify schema includes the fields
    # The endpoint returns list[AgentApiConfigView] which should have the new fields
    for cfg in configs:
        assert "tavily_api_key_env" in cfg
        assert "firecrawl_api_key_env" in cfg
        break


def test_search_clients_importable():
    """Verify Tavily and Firecrawl clients can be imported."""
    from app.search import TavilyClient, FirecrawlClient
    assert TavilyClient is not None
    assert FirecrawlClient is not None


def test_tavily_client_instantiation():
    """Verify TavilyClient can be instantiated (no API call made)."""
    from app.search import TavilyClient
    client = TavilyClient(api_key="test-key")
    assert client is not None


def test_firecrawl_client_instantiation():
    """Verify FirecrawlClient can be instantiated (no API call made)."""
    from app.search import FirecrawlClient
    client = FirecrawlClient(api_key="test-key")
    assert client is not None


def test_runtime_accepts_search_keys():
    """Verify run_shop_profile_analysis accepts tavily/firecrawl api key params."""
    import inspect
    from app.agents.runtime import AgentsRuntime
    rt = AgentsRuntime()
    sig = inspect.signature(rt.run_shop_profile_analysis)
    params = list(sig.parameters.keys())
    assert "tavily_api_key" in params
    assert "firecrawl_api_key" in params
```

- [ ] **Step 2: Run tests**

```bash
uv run pytest tests/test_shop_analysis.py -v --tb=short
```
Expected: all tests pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_shop_analysis.py
git commit -m "test: add search client and config field tests for shop_analyst v2"
```

---

### Task 9: Final integration and verification

- [ ] **Step 1: Verify app starts cleanly**

```bash
uv run python -c "from app.main import create_app; app = create_app(); print('App OK, routes:', len(app.routes))"
```

- [ ] **Step 2: Run full test suite**

```bash
uv run pytest tests/ -v --tb=short
```

- [ ] **Step 3: Manual QA checklist**

```
[ ] Navigate to /dashboard/agent-apis — Shop Analyst has 3 rows: LLM, Tavily, Firecrawl
[ ] Tavily/Firecrawl rows show "-" for Provider/Model columns
[ ] Can set API Key Env for Tavily row (e.g., "TAVILY_API_KEY")
[ ] Can set API Key Env for Firecrawl row (e.g., "FIRECRAWL_API_KEY")
[ ] Navigate to /dashboard/shop-analysis — page loads
[ ] Run an analysis with valid store URL — search data appears in results
[ ] GmMemory entries include search_errors field when tools unavailable
```

- [ ] **Step 4: Final commit (if any cleanup needed)**

```bash
git add -A
git commit -m "feat: complete Tavily + Firecrawl search integration for shop_analyst"
```

# Crispy

ROI-focused multi-agent ad creative pipeline for cross-border ecommerce.

## MVP scope
- Semi-automated and human-reviewable pipeline.
- Stage graph is mode-based:
  - `copy_image_only`: `intake -> planning -> divergence -> copy_image_generation -> evaluation_selection`
  - `video_only`: `intake -> planning -> divergence -> video_scripting -> storyboard_image_generation -> video_generation -> evaluation_selection`
  - `full_multimodal`: all 8 stages end-to-end
- Multi-agent roles: GM orchestrator + stage agents + compliance policy.
- Structured contracts via Pydantic and persisted JSONB/JSON.
- Feedback loop with CSV import and weighted leaderboard.

## Agent responsibilities
- Crispy treats **stages** and **agents** as decoupled layers. Stages are workflow checkpoints; agents are capability roles.
- Current stage-to-agent mapping:
  - `gm_orchestrator`: `intake`
  - `ideation_agent`: `planning`, `divergence`
  - `generation_agent`: `copy_image_generation`, `video_scripting`, `storyboard_image_generation`, `video_generation`
  - `scoring_agent`: `evaluation_selection`
- `product_research_agent` and `compliance_agent` are still first-class personas, but in current MVP flow:
  - autonomous research is optional (`enable_research=false` by default), so no standalone research stage is always executed;
  - compliance checks are included in evaluation outputs rather than a separate mandatory stage.
- Source of truth for runtime mapping: `app/agents/registry.py`.

## Stack
- Python 3.11+
- `uv` for environment and dependency management
- `FastAPI` + `uvicorn` for API and lightweight dashboard
- `SQLAlchemy` with PostgreSQL-compatible JSONB modeling
- `Pydantic` for strict inter-agent contracts
- `CrewAI` dependency reserved for deeper runtime integration in phase 2

## Quick start

### Use uv
```bash
uv sync
```

### API key management — one convention for everything

**Every configuration value in Crispy uses `CRISPY_API_KEY_*`.** There are no other env var prefixes. All of them — LLM keys, platform tokens, database IDs, account IDs — live under this single namespace and are auto-discovered by the configs page.

```
CRISPY_API_KEY_OPENAI              # OpenAI API key
CRISPY_API_KEY_DEEPSEEK            # DeepSeek API key
CRISPY_API_KEY_KIMI                # Kimi / Moonshot API key
CRISPY_API_KEY_NOTION              # Notion internal integration token
CRISPY_API_KEY_NOTION_DATABASE     # Notion content calendar database ID
CRISPY_API_KEY_SHOPIFY             # Shopify access token (reserved)
CRISPY_API_KEY_META                # Meta Ads access token (reserved)
```

#### How it works end-to-end

1. **You** set `export CRISPY_API_KEY_OPENAI="sk-..."` in `~/.zshrc`.
2. **Configs page** (`/dashboard/agent-apis`) calls `list_api_key_env_names()` which scans `os.environ` for all vars starting with `CRISPY_API_KEY_`. These appear as dropdown options in the Agent API Configs UI and as entries in the Integration Configs section.
3. **You** assign a key to an agent by selecting it from the dropdown. The configs page writes only the *env var name* (e.g. `CRISPY_API_KEY_OPENAI`) to the `agent_api_config` table. The actual key value is never stored in the database.
4. **Runtime** calls `resolve_agent_runtime()` which reads the env var name from the DB, then calls `os.getenv("CRISPY_API_KEY_OPENAI")` to get the actual key value. Integration providers (Notion, Shopify, Meta) also read directly via `os.getenv("CRISPY_API_KEY_*")`.

```
~/.zshrc                    Configs page DB              Runtime
─────────                   ───────────────              ───────
export CRISPY_API_KEY_      agent_api_config             resolve_agent_runtime()
  OPENAI="sk-..."    →      api_key_env =                os.getenv(
                              "CRISPY_API_KEY_OPENAI"      "CRISPY_API_KEY_OPENAI")
                                                        → "sk-..."
export CRISPY_API_KEY_      IntegrationConfig            os.getenv(
  NOTION="ntn_..."   →      env_var =                      "CRISPY_API_KEY_NOTION")
                              "CRISPY_API_KEY_NOTION"    → "ntn_..."
```

#### Setting up credentials

Add to `~/.zshrc` (or `~/.zprofile`):

```bash
# ── LLM API keys ──
export CRISPY_API_KEY_OPENAI="sk-your-openai-key"
export CRISPY_API_KEY_DEEPSEEK="sk-your-deepseek-key"
export CRISPY_API_KEY_KIMI="sk-your-kimi-key"

# ── Notion calendar integration ──
export CRISPY_API_KEY_NOTION="ntn_your-notion-internal-integration-token"
export CRISPY_API_KEY_NOTION_DATABASE="your-notion-database-32char-id"

# ── Shopify (reserved) ──
export CRISPY_API_KEY_SHOPIFY="shpat_your-shopify-access-token"

# ── Meta Ads (reserved) ──
export CRISPY_API_KEY_META="EAA..."
```

Apply and verify:

```bash
source ~/.zshrc

# Verify — every CRISPY_API_KEY_* var should appear
env | grep CRISPY_API_KEY | sort

# Start the app
uv run uvicorn app.main:app --reload
```

Open `/dashboard/agent-apis` — the dropdown and the Integration Configs section both list everything under `CRISPY_API_KEY_*`. The configs page shows `is_set: true` for every var that has a value.

#### Architecture — single resolution path

```
CRISPY_API_KEY_*  ──→  list_api_key_env_names()   ──→  Configs page dropdown
  (env vars)            os.environ scan                  AgentApiConfig.api_key_env (DB)
                     ──→  list_integration_configs() ──→  IntegrationConfig.env_var (DB)
                                                         resolve_agent_runtime() → actual key
                                                         os.getenv() → actual key
```

**One rule**: everything lives under `CRISPY_API_KEY_*`. If you need a new credential, you name it `CRISPY_API_KEY_<PURPOSE>` and it's automatically visible everywhere.

### Dashboard:

```bash
uv run uvicorn app.main:app --reload
```

Open dashboard
- [http://localhost:8000](http://localhost:8000)
- [http://localhost:8000/dashboard/agent-apis](http://localhost:8000/dashboard/agent-apis) for agent API config management



## Key API endpoints
- `GET /runs` list latest runs (dashboard feed)
- `POST /runs` create a pipeline run (JSON)
- `POST /runs/rich` create a pipeline run with multipart files (SKU/image/video/url references)
- `GET /pipeline-modes` list available pipeline modes with stage+agent coverage
- `GET /creative-presets` list built-in creative size/duration presets
- `GET /runs/{id}` inspect run and stage outputs
- `GET /runs/{id}/deliverables` get selected best deliverables
- `GET /runs/{id}/variants` get divergence variants and ranked results
- `POST /runs/{id}/advance` approve current stage and queue next stage
- `POST /runs/{id}/reject` reject and requeue current stage
- `POST /feedback/import` import weekly CSV-equivalent rows
- `GET /projects/{id}/leaderboard` get weighted creative ranking
- `GET /personas` list persona catalog (GM and stage agents)
- `GET /personas/{agent}` read persona markdown
- `PATCH /personas/{agent}` update persona markdown + create audit version
- `GET /agent-configs` list default + per-agent API configs
- `GET /agent-configs/env-vars` list discovered env vars (`CRISPY_API_KEY_` prefix only)
- `PATCH /agent-configs/{agent}` upsert per-agent API config (fallback to `default` if unset)
- `GET /gm-memory` inspect GM memory entries by scope/product/industry
- `POST /integrations/shopify/sync` trigger Shopify product/order data sync
- `POST /integrations/meta/sync` trigger Meta campaign/performance data sync
- `GET /integrations/sync-status` query sync history for a project
- `GET /integrations/shopify/products` list products linked to Shopify
- `GET /integrations/meta/campaigns` list campaigns linked to Meta

## Current pipeline flow (with GM memory loop)
1. Input product/task/materials with required `product_code`, `industry_code`, and `creative_preset` (or custom specs).
2. `intake`: GM orchestrator normalizes structured context and uploaded multimodal inputs.
3. `planning`: ideation agent injects **product-level memory first**, then **industry-level memory** for strategy drafting.
4. `divergence`: ideation agent expands variants.
5. Generation chain:
   - copy/image path -> `copy_image_generation`
   - video path -> `video_scripting -> storyboard_image_generation -> video_generation`
6. `evaluation_selection`: scoring agent ranks variants and returns winner deliverables.
7. After launch feedback import:
   - write product-scope and industry-scope GM memories
   - bump GM instruction version
   - next same `product_code` / `industry_code` run reuses those lessons automatically.

## Data chain &amp; attribution

Crispy ingests performance data from two external sources and attributes it at two levels. All data flows into `GmMemory` for consumption by the planning agent.

### Data sources

```
Shopify Admin API ──→ ShopifyProvider ──→ Product metadata enrichment
                                     ──→ GmMemory (product + store scope)

Meta Marketing API ──→ MetaProvider ──→ FeedbackRow[]
                                     ──→ import_feedback_rows()
                                     ──→ PerformanceSnapshot
                                     ──→ GmMemory (product + industry scope)
                                     ──→ GmMemory (store scope)
```

### Attribution hierarchy

| Level | Scope | Source | Consumer |
|---|---|---|---|
| **Product** (primary) | `memory_scope="product"` | Shopify orders via SKU matching, Meta ads via Campaign→Product chain | Planning agent creative strategy |
| **Store** (secondary) | `memory_scope="shop"` | Shopify/Meta aggregate metrics across all products | Cross-product context, industry benchmarks |
| **Industry** | `memory_scope="industry"` | FeedbackRow with `industry_code` from PipelineRun or sync | Industry-level pattern memory |

### Attribution logic

- **Shopify → Product**: Order line items matched to `Product.product_code` via variant SKU. Unmatched items are skipped.
- **Meta → Product**: Ad insights matched to `Campaign.platform_campaign_id`, then resolved through `Campaign.product_id → Product.product_code`. Ads without a linked product still produce `PerformanceSnapshot` but skip product-level `GmMemory`.
- **Shopify → Store**: Aggregated total revenue, quantity, and product count across all matched products.
- **Meta → Store**: Aggregated total spend, revenue, impressions, clicks, conversions, and creative count across all ad insights.
- **Industry**: Set from `Workspace.industry_code` during sync, or from `PipelineRun.industry_code` during feedback import.

### GmMemory source_type reference

| source_type | memory_type | Scope | Origin |
|---|---|---|---|
| `shopify_sync` | `product_intelligence` | product | Shopify order aggregation |
| `shopify_sync` | `store_intelligence` | shop | Shopify store-level aggregation |
| `meta_sync` | `store_intelligence` | shop | Meta ad account aggregation |
| `feedback_import` | `strategy` | product / industry | Manual CSV import or Meta sync via FeedbackRow pipeline |

## Real API adapter notes
- Provider adapter now supports OpenAI-compatible endpoints for:
  - chat: `/chat/completions`
  - image generation: `/images/generations`
  - video generation: `/videos/generations`
- Endpoint compatibility rules:
  - if `api_base_url` already points to a full endpoint (for example `.../images/generations`), Crispy calls it directly;
  - if `api_base_url` is a root URL (for example `.../v1`), Crispy appends the expected path;
  - if root URL has no `/v1`, Crispy retries with `/v1/...` fallback for compatibility.
- `generation_agent` supports triple config:
  - text config from top-level fields (`provider_name/model_name/api_base_url/api_key_env`)
  - image config from `extra.image_config` (`provider_name/model_name/api_base_url/api_key_env`)
  - video config from `extra.video_config` (`provider_name/model_name/api_base_url/api_key_env`)

## Notes
- Create Run no longer asks user to choose provider/model; runtime model routing is managed in `Agent API Configs`.
- Dashboard `Research Source` defaults to manual mode (`enable_research=false`) for faster local debugging.
- Persona files are structured as `personas/gm/gm_orchestrator.md` and `personas/stages/0x_*.md`.
- API key security: only `api_key_env` names are stored; runtime reads values from system env.
- Media assets are stored in local filesystem under `assets/<run_id>/`.
- Current mode is single-user and no authentication.

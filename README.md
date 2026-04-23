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
- `research_agent` and `compliance_agent` are still first-class personas, but in current MVP flow:
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

### API Key env naming and zshrc setup
- Crispy only auto-discovers API key env vars with prefix: `CRISPY_API_KEY_`.
- In Agent API config page, `API Key Env` uses dropdown options from current shell environment and writes only the env var name to DB.
- Real key values are never stored in DB.

Example run in terminal app, or write directly in your `~/.zshrc`:
```bash
# Crispy API keys (detected by /dashboard/agent-apis dropdown)
echo 'export CRISPY_API_KEY_OPENAI="your-openai-key"' >> /.zshrc
```

Apply changes:
```bash
source ~/.zshrc
```

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

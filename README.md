# Crispy

![Crispy](image_task_01KQXWA2114JC5QJ3N92E8A4Z5_0.png)

CRISPY is a semi-automated multi-agent pipeline for ad creative generation — copy, image, and video — with a self-improving feedback loop. Built for e-commerce teams who run paid ads across Meta, TikTok, and Shopify.

## Key Features

**Multi-agent pipeline** — Each stage has a specialized AI persona: orchestrator for intake, ideation agent for strategy, generation agent for creative production, scoring agent for evaluation.

**Self-improving memory** — Performance feedback is stored as product-level and industry-level memory. The planning agent automatically references past winners and avoids past failures.

**Human-in-the-loop** — Every creative stage can pause for review. Promote variants, request regeneration, or set winners before publishing.

**Notion calendar sync** — Schedule approved creatives to a Notion database. Channel, date, status, and crispy links are synced bidirectionally.

**Multi-modal input** — Upload product images and videos as reference. The intake stage analyzes them and feeds visual context to all downstream agents.

**Visual QA** — Generated images are automatically checked for common issues (placeholder detection, aspect ratio, resolution). Marketplace mode adds white background and product fill checks.

**Data source switching** — Switch between SQLite databases at runtime. Useful for separating test data from production data.

## Quick Start

### 1. Install

Requires `uv` and Python 3.11+.

```bash
git clone https://github.com/xolarvill/crispy && cd crispy
uv sync
```

### 2. Add your API keys

```bash
# LLM providers (at least one required)
export CRISPY_API_KEY_OPENAI="sk-..."
export CRISPY_API_KEY_DEEPSEEK="sk-..."
export CRISPY_API_KEY_KIMI="sk-..."

# Notion calendar (optional — for content scheduling)
export CRISPY_API_KEY_NOTION="ntn_..."
export CRISPY_API_KEY_NOTION_DATABASE="your-database-id"
```

All keys use the `CRISPY_API_KEY_*` prefix and are auto-discovered.

> 1. To connect to Notion, add an [Internal Connection](https://www.notion.so/profile/integrations/internal), copy its Installation Access Token as Notion api key. The internal connection will be showed as a user-like bot. Give it content access to a database you choose. Extract the code between `notion.so/` and `?v` in the database's website link. This code is the Notion database key.
> 2. To connect to Meta
> 3. To connect to Shopify

Apply and verify:

```bash
source ~/.zshrc

# Verify — every CRISPY_API_KEY_* var should appear
env | grep CRISPY_API_KEY | sort
```

### 3. Start

```bash
uv run uvicorn app.main:app
```

Open **http://localhost:8000** in your browser.

## Dashboard Tour

| Page | What it does |
|---|---|
| **Dashboard** (home) | Run list, create runs, review & approve/reject stages, view generated creatives |
| **API & Integration Configs** | Assign LLM providers and models to each agent. Save All button at bottom-right |
| **Shop Analysis** | Analyze Shopify stores — products, categories, competitor research |
| **Data Dashboard** | Import performance CSVs, view creative leaderboard, sync Shopify/Meta data |
| **Content Calendar** | Schedule approved creatives to publishing channels. Syncs with Notion |
| **Asset Library** | Browse all generated images and videos across runs |
| **Personas** | View and edit agent prompt personas |

## Core Workflow

1. **Configure agents** — Go to API & Integration Configs, pick providers/models for each agent![API configures](image.png)
2. **Add useful background information** -- Use Shop Analysis to acquire basic information strategy-wise.![Shop Analysis](iShot_2026-05-06_13.27.44.png)
3. **Create a run** — Click the + button, fill in product info, upload reference images/videos![Screenshot](iShot_2026-05-06_13.25.47.png)
4. **Review outputs** — Each stage pauses for human approval (or use semi_auto/full_auto mode)
5. **Schedule winners** — Push approved creatives to Notion Calendar with publish dates
6. **Import feedback** — Upload CSV with ad performance data (impressions, clicks, spend, conversions, revenue). Or use API portals to automatically feedback.
7. **Next run improves** — The planning agent automatically uses winning patterns from past feedback

## Pipeline Modes

| Mode | Use case |
|---|---|
| `copy_image_only` | Static image ads with copy |
| `video_only` | Short video ads (script → storyboard → video) |
| `full_multimodal` | Both copy+image and video in one run |
| `marketplace_main_image` | White-background product main images for Amazon/Shopify/TikTok Shop |
| `tiktok_shop_video` | TikTok-optimized video ads |

## Database Backup

Your database is automatically backed up to `~/.crispy/backups/` every time the server starts. The last 10 backups are kept.

- **Manual backup**: Click "Backup DB" in the dashboard nav bar
- **Restore**: Click "Restore DB", pick a backup from the list
- **Recovery**: `cp ~/.crispy/backups/crispy-YYYY-MM-DD-HHmmss.db crispy.db`



## Technical Details

See **[agents.md](agents.md)** for:
- Full pipeline stage plans and agent mapping
- Data model reference
- Complete API documentation
- Model routing and configuration architecture
- GM Memory system design
- Worker, concurrency, and retry logic
- Development guide (adding stages, providers, etc.)

## Notes

- Single-user mode with no authentication (MVP)
- Media assets stored locally under `assets/<run_id>/`
- SQLite is the default database; PostgreSQL-compatible schema design
- Agent persona files are editable markdown at `personas/`
- Run `uv run pytest tests/ -x -q` to verify everything works

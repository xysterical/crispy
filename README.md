# Crispy

ROI-focused multi-agent ad creative pipeline for cross-border ecommerce.

## MVP scope
- Semi-automated and human-reviewable pipeline.
- Four stages: `research -> ideation -> generation -> scoring`.
- Multi-agent roles: GM orchestrator + stage agents + compliance policy.
- Structured contracts via Pydantic and persisted JSONB/JSON.
- Feedback loop with CSV import and weighted leaderboard.

## Stack
- Python 3.11+
- `uv` for environment and dependency management
- `FastAPI` + `uvicorn` for API and lightweight dashboard
- `SQLAlchemy` with PostgreSQL-compatible JSONB modeling
- `Pydantic` for strict inter-agent contracts
- `CrewAI` dependency reserved for deeper runtime integration in phase 2

## Quick start
```bash
uv sync
uv run uvicorn app.main:app --reload
```

Open dashboard:
- [http://localhost:8000](http://localhost:8000)

## Key API endpoints
- `POST /runs` create a pipeline run
- `GET /runs/{id}` inspect run and stage outputs
- `POST /runs/{id}/advance` approve current stage and queue next stage
- `POST /runs/{id}/reject` reject and requeue current stage
- `POST /feedback/import` import weekly CSV-equivalent rows
- `GET /projects/{id}/leaderboard` get weighted creative ranking
- `GET /personas/{agent}` read persona markdown
- `PATCH /personas/{agent}` update persona markdown + create audit version

## Notes
- Default provider is a local Kimi stub adapter for deterministic MVP behavior.
- Media assets are stored in local filesystem under `assets/<run_id>/`.
- Current mode is single-user and no authentication.

# Create Run UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the Create Run form from a flat 32-field layout into a Progressive Accordion with wizard/expert dual modes, custom-first creative specs, template CRUD, and product code intelligence.

**Architecture:** New models (CreativePreset, RunTemplate) with CRUD services and REST endpoints. Preflight merged into /runs/rich as single round-trip. Dashboard HTML extracted from routes.py into app/dashboard/ module. All fields preserved; interaction model changes only.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy 2.0, SQLite, Pydantic v2, raw HTML/CSS/JS (no framework), pytest

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `app/data/models.py` | Modify | Add CreativePreset, RunTemplate ORM models |
| `app/schemas/api.py` | Modify | Add preset/template Pydantic schemas; add ProductConfigHint schema |
| `app/services/creative_specs.py` | Modify | Add user preset CRUD; list merges system + user presets |
| `app/services/templates.py` | Create | Run template CRUD |
| `app/services/runs.py` | Modify | Add `get_last_product_config()`; integrate preflight into create_run |
| `app/api/routes.py` | Modify | Add CRUD endpoints; merge preflight into /runs/rich; extract dashboard HTML |
| `app/dashboard/__init__.py` | Create | Dashboard module init, re-exports |
| `app/dashboard/create_run.py` | Create | Create Run section HTML/CSS/JS |
| `app/dashboard/layout.py` | Create | Shared layout shell (head, nav, style vars) |
| `tests/test_creative_presets.py` | Create | Preset CRUD + pipeline coupling tests |
| `tests/test_run_templates.py` | Create | Template CRUD tests |
| `tests/test_preflight_inline.py` | Create | Inline preflight in /runs/rich tests |

---

### Task 1: CreativePreset and RunTemplate ORM models

**Files:**
- Modify: `app/data/models.py` — append after existing models (~line 220)

- [ ] **Step 1: Add CreativePreset and RunTemplate models**

```python
# Append to app/data/models.py after the last model class


class CreativePreset(Base):
    __tablename__ = "creative_preset"
    __table_args__ = (UniqueConstraint("workspace_name", "name", name="uq_preset_workspace_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    image_size: Mapped[str | None] = mapped_column(String(16), nullable=True)
    video_size: Mapped[str | None] = mapped_column(String(16), nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(16), nullable=True)
    video_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    platform_targets: Mapped[dict] = mapped_column(json_type(), default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class RunTemplate(Base):
    __tablename__ = "run_template"
    __table_args__ = (UniqueConstraint("workspace_name", "name", name="uq_template_workspace_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    config_json: Mapped[dict] = mapped_column(json_type(), default=dict)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
```

- [ ] **Step 2: Verify models create tables**

Run: `python -c "from app.data.base import Base; from app.data.models import *; print('CreativePreset' in [t.name for t in Base.metadata.tables.values()])"`
Expected: `True`

- [ ] **Step 3: Commit**

```bash
git add app/data/models.py
git commit -m "feat: add CreativePreset and RunTemplate ORM models"
```

---

### Task 2: Pydantic schemas for presets and templates

**Files:**
- Modify: `app/schemas/api.py` — append new schemas

- [ ] **Step 1: Add Pydantic schemas**

```python
# Append to app/schemas/api.py after existing schemas


class CreativePresetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    workspace_name: str = Field(default="workspace_demo")
    image_size: str | None = None
    video_size: str | None = None
    resolution: str | None = None
    video_duration_seconds: int | None = None
    platform_targets: dict = Field(default_factory=dict)


class CreativePresetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    image_size: str | None = None
    video_size: str | None = None
    resolution: str | None = None
    video_duration_seconds: int | None = None
    platform_targets: dict | None = None


class CreativePresetView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_name: str
    name: str
    image_size: str | None = None
    video_size: str | None = None
    resolution: str | None = None
    video_duration_seconds: int | None = None
    platform_targets: dict
    created_at: datetime
    updated_at: datetime


class CreativePresetListResponse(BaseModel):
    system: list[dict]  # system presets as plain dicts
    user: list[CreativePresetView]


class RunTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    workspace_name: str = Field(default="workspace_demo")
    config_json: dict = Field(default_factory=dict)
    is_shared: bool = False


class RunTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    config_json: dict | None = None
    is_shared: bool | None = None


class RunTemplateView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_name: str
    name: str
    config_json: dict
    is_shared: bool
    created_at: datetime
    updated_at: datetime


class ProductConfigHint(BaseModel):
    product_code: str
    pipeline_mode: str | None = None
    approval_mode: str | None = None
    creative_preset: str | None = None
    creative_specs: dict | None = None
    channel: str | None = None
    objective: str | None = None
    last_run_at: datetime | None = None
```

- [ ] **Step 2: Verify schemas import cleanly**

Run: `python -c "from app.schemas.api import CreativePresetCreate, CreativePresetView, RunTemplateCreate, RunTemplateView, ProductConfigHint; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/schemas/api.py
git commit -m "feat: add preset/template Pydantic schemas"
```

---

### Task 3: Creative preset CRUD service

**Files:**
- Modify: `app/services/creative_specs.py`

- [ ] **Step 1: Add CRUD functions to creative_specs.py**

Replace the current `list_creative_presets()` pattern with system + user merging, and add CRUD:

```python
# Replace the file contents of app/services/creative_specs.py

from __future__ import annotations

from copy import deepcopy
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.data.models import CreativePreset

CREATIVE_PRESETS: dict[str, dict] = {
    "meta_square_5s": {
        "image_size": "1:1",
        "video_size": "1:1",
        "resolution": "720p",
        "video_duration_seconds": 5,
    },
    "meta_vertical_5s": {
        "image_size": "9:16",
        "video_size": "9:16",
        "resolution": "720p",
        "video_duration_seconds": 5,
    },
    "youtube_landscape_6s": {
        "image_size": "16:9",
        "video_size": "16:9",
        "resolution": "1080p",
        "video_duration_seconds": 6,
    },
    "marketplace_main_image_pack": {
        "image_size": "1:1",
        "video_size": "1:1",
        "resolution": "2000px",
        "video_duration_seconds": 5,
        "asset_goal": "marketplace_main_image",
        "platform_targets": ["tiktok_shop", "shopify", "alibaba", "amazon"],
        "export_size_px": 2000,
        "background_policy": "pure_white",
    },
}


def list_system_presets() -> dict[str, dict]:
    return deepcopy(CREATIVE_PRESETS)


def list_user_presets(db: Session, workspace_name: str) -> list[CreativePreset]:
    return list(
        db.scalars(
            select(CreativePreset)
            .where(CreativePreset.workspace_name == workspace_name)
            .order_by(CreativePreset.updated_at.desc())
        ).all()
    )


def get_creative_preset(db: Session, preset_id: str) -> CreativePreset:
    preset = db.get(CreativePreset, preset_id)
    if not preset:
        raise ValueError(f"creative preset not found: {preset_id}")
    return preset


def create_creative_preset(db: Session, workspace_name: str, name: str, image_size: str | None = None, video_size: str | None = None, resolution: str | None = None, video_duration_seconds: int | None = None, platform_targets: dict | None = None) -> CreativePreset:
    existing = db.scalar(
        select(CreativePreset).where(
            CreativePreset.workspace_name == workspace_name,
            CreativePreset.name == name,
        )
    )
    if existing:
        raise ValueError(f"creative preset already exists: {name}")
    preset = CreativePreset(
        workspace_name=workspace_name,
        name=name,
        image_size=image_size,
        video_size=video_size,
        resolution=resolution,
        video_duration_seconds=video_duration_seconds,
        platform_targets=platform_targets or {},
    )
    db.add(preset)
    db.flush()
    return preset


def update_creative_preset(db: Session, preset_id: str, **kwargs) -> CreativePreset:
    preset = get_creative_preset(db, preset_id)
    for key, value in kwargs.items():
        if value is not None and hasattr(preset, key):
            setattr(preset, key, value)
    db.flush()
    return preset


def delete_creative_preset(db: Session, preset_id: str) -> None:
    preset = get_creative_preset(db, preset_id)
    db.delete(preset)
    db.flush()


def resolve_creative_specs(creative_preset: str, creative_specs: dict | None = None) -> dict:
    preset = (creative_preset or "").strip()
    custom = dict(creative_specs or {})
    if preset == "custom":
        required = ("image_size", "video_size", "resolution", "video_duration_seconds")
        for key in required:
            if key not in custom or custom[key] in (None, ""):
                raise ValueError(f"creative_specs.{key} is required when creative_preset=custom")
        resolved = custom
    else:
        if preset not in CREATIVE_PRESETS:
            supported = ", ".join(sorted([*CREATIVE_PRESETS.keys(), "custom"]))
            raise ValueError(f"unsupported creative_preset: {preset}; supported={supported}")
        resolved = {**CREATIVE_PRESETS[preset], **custom}

    duration = resolved.get("video_duration_seconds")
    try:
        duration_int = int(duration)
    except Exception as exc:
        raise ValueError("creative_specs.video_duration_seconds must be integer") from exc
    if duration_int <= 0 or duration_int > 60:
        raise ValueError("creative_specs.video_duration_seconds must be within 1..60")
    resolved["video_duration_seconds"] = duration_int
    return resolved


def resolve_creative_specs_from_user_preset(db: Session, preset_id: str) -> dict:
    preset = get_creative_preset(db, preset_id)
    return {
        "image_size": preset.image_size or "1:1",
        "video_size": preset.video_size or "1:1",
        "resolution": preset.resolution or "720p",
        "video_duration_seconds": preset.video_duration_seconds or 5,
        "platform_targets": preset.platform_targets or {},
    }
```

- [ ] **Step 2: Verify service functions work**

Run: `python -c "from app.services.creative_specs import list_system_presets, resolve_creative_specs; assert 'meta_square_5s' in list_system_presets(); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/services/creative_specs.py
git commit -m "feat: add creative preset CRUD service with system+user preset merging"
```

---

### Task 4: Run template CRUD service

**Files:**
- Create: `app/services/templates.py`

- [ ] **Step 1: Create templates.py**

```python
# app/services/templates.py

from __future__ import annotations

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.data.models import RunTemplate


def list_run_templates(db: Session, workspace_name: str) -> list[RunTemplate]:
    return list(
        db.scalars(
            select(RunTemplate)
            .where(RunTemplate.workspace_name == workspace_name)
            .order_by(RunTemplate.updated_at.desc())
        ).all()
    )


def get_run_template(db: Session, template_id: str) -> RunTemplate:
    template = db.get(RunTemplate, template_id)
    if not template:
        raise ValueError(f"run template not found: {template_id}")
    return template


def create_run_template(db: Session, workspace_name: str, name: str, config_json: dict | None = None, is_shared: bool = False) -> RunTemplate:
    existing = db.scalar(
        select(RunTemplate).where(
            RunTemplate.workspace_name == workspace_name,
            RunTemplate.name == name,
        )
    )
    if existing:
        raise ValueError(f"run template already exists: {name}")
    template = RunTemplate(
        workspace_name=workspace_name,
        name=name,
        config_json=config_json or {},
        is_shared=is_shared,
    )
    db.add(template)
    db.flush()
    return template


def update_run_template(db: Session, template_id: str, **kwargs) -> RunTemplate:
    template = get_run_template(db, template_id)
    for key, value in kwargs.items():
        if value is not None and hasattr(template, key):
            setattr(template, key, value)
    db.flush()
    return template


def delete_run_template(db: Session, template_id: str) -> None:
    template = get_run_template(db, template_id)
    db.delete(template)
    db.flush()
```

- [ ] **Step 2: Verify service imports**

Run: `python -c "from app.services.templates import list_run_templates, create_run_template; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/services/templates.py
git commit -m "feat: add run template CRUD service"
```

---

### Task 5: Product code lookup in runs service

**Files:**
- Modify: `app/services/runs.py`

- [ ] **Step 1: Add get_last_product_config function**

```python
# Append to app/services/runs.py


def get_last_product_config(db: Session, product_code: str) -> dict | None:
    """Return the creative config from the most recent run for a given product_code."""
    from sqlalchemy import desc, select as _select
    from app.data.models import PipelineRun as _PipelineRun

    last_run = db.scalar(
        _select(_PipelineRun)
        .where(_PipelineRun.product_code == product_code)
        .order_by(desc(_PipelineRun.created_at))
    )
    if not last_run:
        return None
    return {
        "product_code": product_code,
        "pipeline_mode": last_run.pipeline_mode,
        "approval_mode": last_run.approval_mode,
        "creative_preset": last_run.creative_preset,
        "creative_specs": last_run.creative_specs,
        "channel": last_run.campaign.channel if last_run.campaign else "meta",
        "objective": last_run.campaign.objective if last_run.campaign else "conversions",
        "last_run_at": last_run.created_at,
    }
```

- [ ] **Step 2: Verify function with existing test data**

Run: `pytest tests/test_pipeline_api.py -v -k "test_create" --no-header -q`
Expected: existing tests pass

- [ ] **Step 3: Commit**

```bash
git add app/services/runs.py
git commit -m "feat: add get_last_product_config for product code intelligence"
```

---

### Task 6: Preflight merge into /runs/rich

**Files:**
- Modify: `app/api/routes.py:3451-3543` — the `create_pipeline_run_rich` function
- Modify: `app/services/runs.py:266-329` — the `create_run` function (optional preflight parameter)

- [ ] **Step 1: Modify /runs/rich to run preflight inline and return warnings**

Before the `try: run = create_run(db, payload)` block (around line 3503), insert preflight logic:

```python
# In create_pipeline_run_rich, right after building payload (before create_run):
    # -- inline preflight --
    from app.services.capability_preflight import preflight_run_capabilities

    has_image = any(
        (f.content_type or "").startswith("image/") for f in files
    )
    has_video = any(
        (f.content_type or "").startswith("video/") for f in files
    )
    preflight_result = preflight_run_capabilities(
        db,
        pipeline_mode=pipeline_mode,
        has_image_inputs=has_image or bool(assets_from_previous_upload),
        has_video_inputs=has_video or bool(assets_from_previous_upload),
        creative_specs=payload.creative_specs,
    )
    # -- end inline preflight --
```

Then modify the response construction (around line 3543) to include preflight results in the returned RunView or as a header. Since RunView doesn't have a preflight field, add warnings as a response header or extend RunView:

```python
    # After the existing db.commit() and db.refresh(run):
    result = _serialize_run(db, run)
    result["_preflight"] = preflight_result
    return result
```

The frontend JS will check `data._preflight` in the response and show warnings inline instead of via `window.alert()`.

Note: `_serialize_run` returns a dict, so adding `_preflight` is straightforward.

- [ ] **Step 2: Remove the separate /runs/preflight endpoint usage in frontend JS**

(Will be done in the frontend tasks — just note this dependency.)

- [ ] **Step 3: Verify existing rich run creation still works**

Run: `pytest tests/test_rich_run.py -v --no-header -q`
Expected: existing tests pass

- [ ] **Step 4: Commit**

```bash
git add app/api/routes.py app/services/runs.py
git commit -m "feat: merge preflight capability check into /runs/rich as inline check"
```

---

### Task 7: API endpoints for preset and template CRUD

**Files:**
- Modify: `app/api/routes.py` — add new routes before the dashboard HTML section

- [ ] **Step 1: Add import statements at top of routes.py**

Add to the existing import block (after existing service imports, ~line 91):

```python
from app.services.creative_specs import (
    create_creative_preset,
    delete_creative_preset,
    get_creative_preset,
    list_system_presets,
    list_user_presets,
    update_creative_preset,
)
from app.services.templates import (
    create_run_template,
    delete_run_template,
    get_run_template,
    list_run_templates,
    update_run_template,
)
from app.services.runs import get_last_product_config
from app.schemas.api import (
    CreativePresetCreate,
    CreativePresetListResponse,
    CreativePresetUpdate,
    CreativePresetView,
    ProductConfigHint,
    RunTemplateCreate,
    RunTemplateUpdate,
    RunTemplateView,
)
```

- [ ] **Step 2: Add CRUD endpoint routes**

Insert after the existing `get_creative_presets()` function (~line 3370) and before `/runs/preflight`:

```python
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
```

- [ ] **Step 3: Verify new endpoints**

Run: `python -c "from app.main import create_app; app = create_app(); routes = [r.path for r in app.routes]; print('creative-presets' in str(routes)); print('run-templates' in str(routes))"`
Expected: `True` `True`

- [ ] **Step 4: Commit**

```bash
git add app/api/routes.py
git commit -m "feat: add CRUD endpoints for creative presets, run templates, and product config hint"
```

---

### Task 8: Write tests for creative presets

**Files:**
- Create: `tests/test_creative_presets.py`

- [ ] **Step 1: Write the tests**

```python
# tests/test_creative_presets.py

from __future__ import annotations


def test_list_presets_includes_system(client):
    resp = client.get("/creative-presets?workspace_name=test_ws")
    assert resp.status_code == 200
    body = resp.json()
    assert "system" in body
    assert "user" in body
    system_keys = [p["key"] for p in body["system"]]
    assert "meta_square_5s" in system_keys
    assert "meta_vertical_5s" in system_keys


def test_create_and_list_user_preset(client):
    resp = client.post(
        "/creative-presets",
        json={
            "name": "TikTok Vertical",
            "workspace_name": "test_ws",
            "image_size": "9:16",
            "video_size": "9:16",
            "resolution": "720p",
            "video_duration_seconds": 30,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "TikTok Vertical"
    assert data["image_size"] == "9:16"
    preset_id = data["id"]

    list_resp = client.get("/creative-presets?workspace_name=test_ws")
    assert list_resp.status_code == 200
    user_presets = list_resp.json()["user"]
    assert any(p["id"] == preset_id for p in user_presets)


def test_update_preset(client):
    resp = client.post(
        "/creative-presets",
        json={"name": "Old Name", "workspace_name": "test_ws", "image_size": "1:1"},
    )
    preset_id = resp.json()["id"]

    update = client.put(
        f"/creative-presets/{preset_id}",
        json={"name": "New Name", "resolution": "1080p"},
    )
    assert update.status_code == 200
    assert update.json()["name"] == "New Name"
    assert update.json()["resolution"] == "1080p"


def test_delete_preset(client):
    resp = client.post(
        "/creative-presets",
        json={"name": "To Delete", "workspace_name": "test_ws", "image_size": "1:1"},
    )
    preset_id = resp.json()["id"]

    delete = client.delete(f"/creative-presets/{preset_id}")
    assert delete.status_code == 204

    list_resp = client.get("/creative-presets?workspace_name=test_ws")
    assert not any(p["id"] == preset_id for p in list_resp.json()["user"])


def test_duplicate_preset_name_conflict(client):
    client.post(
        "/creative-presets",
        json={"name": "Unique", "workspace_name": "test_ws", "image_size": "1:1"},
    )
    resp = client.post(
        "/creative-presets",
        json={"name": "Unique", "workspace_name": "test_ws", "image_size": "9:16"},
    )
    assert resp.status_code == 409


def test_preset_not_found(client):
    resp = client.put(
        "/creative-presets/nonexistent-id",
        json={"name": "X"},
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_creative_presets.py -v`
Expected: 6 passed

- [ ] **Step 3: Commit**

```bash
git add tests/test_creative_presets.py
git commit -m "test: add creative preset CRUD tests"
```

---

### Task 9: Write tests for run templates

**Files:**
- Create: `tests/test_run_templates.py`

- [ ] **Step 1: Write the tests**

```python
# tests/test_run_templates.py

from __future__ import annotations


def test_create_and_list_template(client):
    resp = client.post(
        "/run-templates",
        json={
            "name": "Dog Leash Meta Campaign",
            "workspace_name": "test_ws",
            "config_json": {
                "pipeline_mode": "full_multimodal",
                "variant_count": 8,
                "channel": "meta",
            },
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Dog Leash Meta Campaign"
    assert data["config_json"]["pipeline_mode"] == "full_multimodal"
    template_id = data["id"]

    list_resp = client.get("/run-templates?workspace_name=test_ws")
    assert list_resp.status_code == 200
    assert any(t["id"] == template_id for t in list_resp.json())


def test_update_template(client):
    resp = client.post(
        "/run-templates",
        json={"name": "Old Template", "workspace_name": "test_ws", "config_json": {"x": 1}},
    )
    template_id = resp.json()["id"]

    update = client.put(
        f"/run-templates/{template_id}",
        json={"name": "Renamed Template", "config_json": {"x": 2}},
    )
    assert update.status_code == 200
    assert update.json()["name"] == "Renamed Template"
    assert update.json()["config_json"]["x"] == 2


def test_delete_template(client):
    resp = client.post(
        "/run-templates",
        json={"name": "To Delete", "workspace_name": "test_ws", "config_json": {}},
    )
    template_id = resp.json()["id"]

    delete = client.delete(f"/run-templates/{template_id}")
    assert delete.status_code == 204

    list_resp = client.get("/run-templates?workspace_name=test_ws")
    assert not any(t["id"] == template_id for t in list_resp.json())


def test_duplicate_template_name_conflict(client):
    client.post(
        "/run-templates",
        json={"name": "Dup", "workspace_name": "test_ws", "config_json": {}},
    )
    resp = client.post(
        "/run-templates",
        json={"name": "Dup", "workspace_name": "test_ws", "config_json": {}},
    )
    assert resp.status_code == 409


def test_template_not_found(client):
    resp = client.put("/run-templates/nonexistent-id", json={"name": "X"})
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_run_templates.py -v`
Expected: 5 passed

- [ ] **Step 3: Commit**

```bash
git add tests/test_run_templates.py
git commit -m "test: add run template CRUD tests"
```

---

### Task 10: Write tests for product config hint and inline preflight

**Files:**
- Create: `tests/test_preflight_inline.py`

- [ ] **Step 1: Write the tests**

```python
# tests/test_preflight_inline.py

from __future__ import annotations


def test_product_config_hint_returns_none_for_unknown(client):
    resp = client.get("/product-config-hint?product_code=NOEXIST")
    assert resp.status_code == 200
    assert resp.json() is None


def test_product_config_hint_after_run(client):
    # create a run first
    run_resp = client.post(
        "/runs",
        json={
            "workspace_name": "hint_ws",
            "project_name": "hint_project",
            "product_name": "hint_product",
            "product_code": "HINT-001",
            "industry_code": "pet",
            "campaign_name": "hint_camp",
            "creative_preset": "meta_square_5s",
            "pipeline_mode": "video_only",
            "approval_mode": "semi_auto",
        },
    )
    assert run_resp.status_code == 200

    hint_resp = client.get("/product-config-hint?product_code=HINT-001")
    assert hint_resp.status_code == 200
    hint = hint_resp.json()
    assert hint is not None
    assert hint["product_code"] == "HINT-001"
    assert hint["pipeline_mode"] == "video_only"
    assert hint["approval_mode"] == "semi_auto"


def test_rich_run_includes_preflight_warnings(client):
    import io
    resp = client.post(
        "/runs/rich",
        data={
            "workspace_name": "pf_ws",
            "project_name": "pf_project",
            "product_name": "pf_product",
            "product_code": "PF-001",
            "industry_code": "pet",
            "campaign_name": "pf_camp",
            "creative_preset": "meta_square_5s",
            "pipeline_mode": "copy_image_only",
            "variant_count": 4,
        },
        files=[("files", ("test.png", io.BytesIO(b"fake-png"), "image/png"))],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "_preflight" in body
    assert "severity" in body["_preflight"]
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_preflight_inline.py -v`
Expected: 3 passed

- [ ] **Step 3: Commit**

```bash
git add tests/test_preflight_inline.py
git commit -m "test: add product config hint and inline preflight tests"
```

---

### Task 11: Extract dashboard into app/dashboard/ module

**Files:**
- Create: `app/dashboard/__init__.py`
- Create: `app/dashboard/layout.py`
- Create: `app/dashboard/create_run.py`
- Modify: `app/api/routes.py` — replace `_dashboard_html()` body with call to new module

- [ ] **Step 1: Create `app/dashboard/__init__.py`**

```python
# app/dashboard/__init__.py

from app.dashboard.layout import render_dashboard

__all__ = ["render_dashboard"]
```

- [ ] **Step 2: Create `app/dashboard/layout.py`**

Extract the shared shell (HTML head, style, nav, layout skeleton) from `_dashboard_html()`. This is the outer frame that wraps page content.

```python
# app/dashboard/layout.py

from __future__ import annotations


SHARED_STYLES = """
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
.hero { display: flex; justify-content: space-between; align-items: flex-end; gap: 12px; margin-bottom: 14px; }
h1, h2, h3 { margin: 0; line-height: 1.25; }
h1 { font-size: 28px; letter-spacing: -0.02em; }
h2 { font-size: 20px; margin-bottom: 10px; }
h3 { font-size: 15px; margin-bottom: 8px; }
.card {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 20px 22px;
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.04);
}
.card h2 { margin-top: 0; }
.row { display: flex; gap: 14px; flex-wrap: wrap; }
.row > div { flex: 1 1 180px; }
label { display: block; font-weight: 600; font-size: 13px; margin-bottom: 3px; color: var(--text); }
input, select, textarea {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 10px 12px;
  font-family: inherit;
  font-size: 14px;
  background: #fff;
  color: var(--text);
  resize: vertical;
}
input:focus, select:focus, textarea:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(31, 122, 98, 0.15); }
input:disabled, select:disabled { background: #f3f4f6; color: #9ca3af; }
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
button:hover { background: var(--soft); }
button.primary { background: var(--accent); color: #fff; border-color: var(--accent); }
button.primary:hover { background: var(--accent-dark); }
.hint { font-size: 12px; margin-top: 4px; }
.muted { color: var(--muted); }
.status-msg { margin-top: 10px; font-weight: 600; }
.action-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.run-detail-empty { color: var(--muted); text-align: center; padding: 32px 0; }

/* accordion / wizard specific */
.accordion { border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; }
.accordion-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 18px; cursor: pointer; background: #fff; border-bottom: 1px solid var(--line);
  font-weight: 600; font-size: 14px;
}
.accordion-header:hover { background: var(--soft); }
.accordion-header:last-child { border-bottom: none; }
.accordion-body { padding: 16px 18px; display: none; background: #fafbfa; }
.accordion-body.open { display: block; }
.accordion-header .chevron { transition: transform 0.2s; }
.accordion-header.open .chevron { transform: rotate(90deg); }

.wizard-sidebar { width: 160px; }
.wizard-step { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-radius: 8px; font-size: 13px; cursor: pointer; }
.wizard-step.active { background: #e0f2fe; color: #2563eb; font-weight: 600; }
.wizard-step.done { color: #059669; }
.wizard-step.pending { color: #9ca3af; }

.file-drop-zone {
  border: 2px dashed var(--line); border-radius: 12px; padding: 24px; text-align: center;
  background: #fafbfa; transition: border-color 0.2s;
}
.file-drop-zone:hover { border-color: var(--accent); }
.file-preview-grid { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
.file-preview-thumb { width: 60px; height: 60px; border-radius: 8px; object-fit: cover; background: #e5e7eb; }
.file-preview-thumb.video { position: relative; }
.file-preview-thumb.video::after { content: "▶"; position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: #fff; font-size: 16px; background: rgba(0,0,0,0.2); border-radius: 8px; }

.quick-fill-bar { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.spec-row { display: flex; gap: 8px; }
.spec-field { flex: 1; min-width: 80px; }
.template-bar { display: flex; align-items: center; gap: 10px; padding: 10px 16px; background: #f9fafb; border-radius: var(--radius); margin-bottom: 14px; border: 1px solid var(--line); }
.template-bar select { width: auto; min-width: 180px; }
.preset-popover { position: absolute; background: #fff; border: 1px solid var(--line); border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.1); z-index: 100; min-width: 280px; }
.preset-section-label { font-size: 10px; font-weight: 700; text-transform: uppercase; color: #9ca3af; padding: 8px 14px 2px; }
.preset-item { padding: 6px 14px; font-size: 13px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; }
.preset-item:hover { background: var(--soft); }
.preset-item-actions { display: flex; gap: 4px; visibility: hidden; }
.preset-item:hover .preset-item-actions { visibility: visible; }
.tab-nav { display: flex; gap: 0; border-bottom: 2px solid var(--line); margin-bottom: 4px; }
.tab-btn { padding: 8px 16px; border: none; background: none; cursor: pointer; font-weight: 600; font-size: 13px; color: var(--muted); border-bottom: 2px solid transparent; margin-bottom: -2px; }
.tab-btn.active { color: var(--accent); border-bottom-color: var(--accent); }
"""


def render_head(title: str = "Crispy Dashboard") -> str:
    return f"""<html>
  <head>
    <title>{title}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>{SHARED_STYLES}</style>
  </head>"""


def render_shell_top() -> str:
    return """  <body>
    <div class="app-shell">
      <div class="hero">
        <h1>Crispy</h1>
        <div class="action-row" style="gap:6px;">
          <a href="/dashboard" style="font-size:13px;">Dashboard</a>
          <a href="/dashboard/assets" style="font-size:13px;">Assets</a>
          <a href="/dashboard/personas" style="font-size:13px;">Personas</a>
          <a href="/dashboard/agent-apis" style="font-size:13px;">Agent APIs</a>
        </div>
      </div>
      <div style="display:flex;gap:20px;flex-wrap:wrap;">
        <div style="flex:1 1 420px;min-width:0;">"""


def render_shell_bottom() -> str:
    return """        </div>
        <div style="flex:0 0 480px;min-width:0;">
          <section class="card" style="margin-bottom:18px;">
            <h2>Runs</h2>
            <div id="runs-list" class="muted">Loading...</div>
          </section>
          <section class="card" style="margin-top:18px;">
            <h2>Run Detail</h2>
            <div id="run-detail" class="run-detail-empty">Select a run.</div>
          </section>
        </div>
      </div>
    </div>"""


def render_dashboard(create_run_html: str, shared_js: str) -> str:
    return (
        render_head()
        + render_shell_top()
        + create_run_html
        + render_shell_bottom()
        + shared_js
        + "\n  </body>\n</html>"
    )
```

- [ ] **Step 3: Create `app/dashboard/create_run.py`** with the accordion-based Create Run form

This is the bulk of the new UI. It contains the HTML for the template bar, the 4 accordion sections, and the file upload zone, plus the accompanying JS.

```python
# app/dashboard/create_run.py

from __future__ import annotations


CREATE_RUN_HTML = """
            <!-- Template Bar -->
            <div class="template-bar" id="template-bar">
              <span style="font-weight:600;font-size:13px;">Load Template:</span>
              <select id="template-selector" onchange="loadTemplate()">
                <option value="">-- choose or type to save new --</option>
              </select>
              <button onclick="applyTemplate()">Apply</button>
              <span style="color:var(--line);margin:0 4px;">|</span>
              <button onclick="saveAsTemplate()">Save Current as Template</button>
              <button onclick="renameTemplate()" id="btn-rename-tpl" disabled>Rename</button>
              <button onclick="deleteTemplate()" id="btn-delete-tpl" disabled style="color:var(--danger);">Delete</button>
            </div>

            <!-- Mode Toggle -->
            <div class="action-row" style="margin-bottom:12px;justify-content:flex-end;">
              <span style="font-size:12px;color:var(--muted);">Mode:</span>
              <button class="tab-btn active" id="mode-guided" onclick="switchMode('guided')">Guided</button>
              <button class="tab-btn" id="mode-expert" onclick="switchMode('expert')">Expert</button>
            </div>

            <!-- Wizard Sidebar + Accordion Container -->
            <div style="display:flex;gap:16px;">
              <div class="wizard-sidebar" id="wizard-sidebar" style="display:flex;flex-direction:column;gap:4px;">
                <div class="wizard-step active" data-step="1" onclick="goToStep(1)"><span class="step-badge">1</span> Product & Assets</div>
                <div class="wizard-step pending" data-step="2" onclick="goToStep(2)"><span class="step-badge">2</span> Platform & Creative</div>
                <div class="wizard-step pending" data-step="3" onclick="goToStep(3)"><span class="step-badge">3</span> Campaign & Targeting</div>
                <div class="wizard-step pending" data-step="4" onclick="goToStep(4)"><span class="step-badge">4</span> Research & Context</div>
              </div>

              <div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:10px;">

                <!-- Section 1: Product & Assets -->
                <div class="accordion" data-section="1">
                  <div class="accordion-header open" onclick="toggleSection(this)">
                    <span>1. Product & Assets</span>
                    <span class="chevron">▸</span>
                  </div>
                  <div class="accordion-body open">
                    <div class="file-drop-zone" id="file-drop-zone" ondragover="event.preventDefault()" ondrop="handleDrop(event)">
                      <div style="font-size:22px;margin-bottom:4px;">&#128247;</div>
                      <div style="font-weight:600;font-size:13px;">Drop product images & videos here</div>
                      <div class="hint muted">PNG, JPG, WebP, MP4, MOV &middot; Max 10 files &middot; 50MB each</div>
                      <input id="input_files" type="file" multiple accept=".csv,.xlsx,.png,.jpg,.jpeg,.webp,.mp4,.mov,.m4v" style="display:none;" onchange="refreshFilePreviews()" />
                      <button onclick="document.getElementById('input_files').click(); return false;" style="margin-top:8px;">Browse Files</button>
                    </div>
                    <div class="file-preview-grid" id="file-preview-grid"></div>
                    <div class="row" style="margin-top:10px;">
                      <div><label>Product Code (required)</label><input id="product_code" value="DL-001" required onblur="checkProductHint()" /></div>
                      <div><label>Product Name</label><input id="product_name" value="dog leash" /></div>
                    </div>
                    <div id="product-hint" class="hint" style="display:none;"></div>
                    <div class="row">
                      <div><label>Workspace</label><input id="workspace_name" value="workspace_demo" /></div>
                      <div><label>Project</label><input id="project_name" value="project_demo" /></div>
                    </div>
                    <div class="row">
                      <div><label>Campaign</label><input id="campaign_name" value="meta_dog_leash_1" /></div>
                      <div><label>Industry Code (required)</label><input id="industry_code" value="pet_accessories" required /></div>
                    </div>
                    <div class="action-row" style="justify-content:flex-end;margin-top:8px;">
                      <button class="primary" onclick="nextStep(1)">Next: Platform & Creative →</button>
                    </div>
                  </div>
                </div>

                <!-- Section 2: Platform & Creative -->
                <div class="accordion" data-section="2">
                  <div class="accordion-header" onclick="toggleSection(this)">
                    <span>2. Platform & Creative</span>
                    <span class="chevron">▸</span>
                  </div>
                  <div class="accordion-body">
                    <div class="row">
                      <div><label>Pipeline Mode</label><select id="pipeline_mode" onchange="refreshPipelineFields()"></select></div>
                      <div><label>Approval Mode</label><select id="approval_mode"><option value="manual" selected>Manual</option><option value="semi_auto">Semi-Auto</option><option value="full_auto">Full-Auto</option></select></div>
                    </div>
                    <div class="row">
                      <div><label>Variant Count</label><input id="variant_count" type="number" min="1" max="16" value="8" /></div>
                      <div><label>Channel</label><input id="channel" value="meta" /></div>
                    </div>
                    <div id="mode-summary" class="hint muted">Loading pipeline modes...</div>

                    <!-- Creative Specs -->
                    <div style="margin-top:8px;">
                      <div class="quick-fill-bar">
                        <span style="font-weight:600;font-size:13px;">Creative Specs</span>
                        <select id="quick-fill-preset" onchange="applyQuickFill()" style="width:auto;min-width:200px;">
                          <option value="">Quick Fill...</option>
                        </select>
                        <button onclick="saveCurrentAsCreativePreset()" title="Save as preset">+ Save</button>
                        <button onclick="manageCreativePresets()" title="Manage presets">&#9881;</button>
                      </div>
                      <div class="spec-row">
                        <div class="spec-field" id="field-image-size"><label>Image Size</label><input id="image_size" value="1:1" placeholder="1:1" /></div>
                        <div class="spec-field" id="field-video-size"><label>Video Size</label><input id="video_size" value="1:1" placeholder="1:1" /></div>
                        <div class="spec-field"><label>Resolution</label><input id="resolution" value="720p" placeholder="720p" /></div>
                        <div class="spec-field" id="field-video-duration"><label>Duration (s)</label><input id="video_duration_seconds" type="number" min="1" max="60" value="5" /></div>
                      </div>
                      <div id="marketplace-fields" style="display:none;margin-top:6px;">
                        <label>Marketplace Targets</label>
                        <div class="action-row" style="gap:6px;flex-wrap:wrap;">
                          <label style="display:flex;align-items:center;gap:4px;font-weight:600;font-size:12px;"><input id="platform_tiktok_shop" type="checkbox" checked /> TikTok Shop</label>
                          <label style="display:flex;align-items:center;gap:4px;font-weight:600;font-size:12px;"><input id="platform_shopify" type="checkbox" checked /> Shopify</label>
                          <label style="display:flex;align-items:center;gap:4px;font-weight:600;font-size:12px;"><input id="platform_alibaba" type="checkbox" checked /> Alibaba</label>
                          <label style="display:flex;align-items:center;gap:4px;font-weight:600;font-size:12px;"><input id="platform_amazon" type="checkbox" checked /> Amazon</label>
                        </div>
                      </div>
                    </div>

                    <div class="action-row" style="justify-content:space-between;margin-top:8px;">
                      <button onclick="prevStep(2)">← Back: Product & Assets</button>
                      <button class="primary" onclick="nextStep(2)">Next: Campaign & Targeting →</button>
                    </div>
                  </div>
                </div>

                <!-- Section 3: Campaign & Targeting -->
                <div class="accordion" data-section="3">
                  <div class="accordion-header" onclick="toggleSection(this)">
                    <span>3. Campaign & Targeting</span>
                    <span class="chevron">▸</span>
                  </div>
                  <div class="accordion-body">
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
                    <div class="action-row" style="justify-content:space-between;margin-top:8px;">
                      <button onclick="prevStep(3)">← Back: Platform & Creative</button>
                      <button class="primary" onclick="nextStep(3)">Next: Research & Context →</button>
                    </div>
                  </div>
                </div>

                <!-- Section 4: Research & Context -->
                <div class="accordion" data-section="4">
                  <div class="accordion-header" onclick="toggleSection(this)">
                    <span>4. Research & Context</span>
                    <span class="chevron">▸</span>
                  </div>
                  <div class="accordion-body">
                    <label>Research Source</label>
                    <select id="research_mode" onchange="refreshResearchHint()">
                      <option value="manual_validated" selected>Use my validated research (Default)</option>
                      <option value="autonomous_web">Run autonomous web research</option>
                    </select>
                    <div id="research-hint" class="hint muted"></div>
                    <label>Validated Research Notes (optional)</label>
                    <textarea id="manual_research_brief" rows="3" placeholder="Paste your manually validated market notes..."></textarea>
                    <label>Reference URLs (one per line)</label>
                    <textarea id="url_references" rows="2" placeholder="https://example.com/product"></textarea>
                    <label>Advanced Business Context JSON (optional)</label>
                    <textarea id="business_context_extra" rows="3" placeholder='{"landing_page_angle":"premium utility","seasonality":"spring"}'></textarea>
                    <div class="action-row" style="justify-content:space-between;margin-top:8px;">
                      <button onclick="prevStep(4)">← Back: Campaign & Targeting</button>
                      <button class="primary" onclick="submitCreateRun()">Create Run</button>
                    </div>
                  </div>
                </div>

              </div>
            </div>
            <div id="create-msg" class="status-msg muted"></div>
"""

# JavaScript shared across dashboard pages
CREATE_RUN_JS = """
<script>
  // ── State ──
  let currentMode = localStorage.getItem('crispy_create_mode') || 'guided';
  let currentStep = 1;
  let lastProductConfig = null;

  // ── Mode Switching ──
  function switchMode(mode) {
    currentMode = mode;
    localStorage.setItem('crispy_create_mode', mode);
    document.getElementById('mode-guided').classList.toggle('active', mode === 'guided');
    document.getElementById('mode-expert').classList.toggle('active', mode === 'expert');
    document.getElementById('wizard-sidebar').style.display = mode === 'guided' ? 'flex' : 'none';
    if (mode === 'expert') {
      document.querySelectorAll('.accordion-body').forEach(b => b.classList.add('open'));
      document.querySelectorAll('.accordion-header').forEach(h => h.classList.add('open'));
    } else {
      document.querySelectorAll('.accordion-body').forEach(b => b.classList.remove('open'));
      document.querySelectorAll('.accordion-header').forEach(h => h.classList.remove('open'));
      document.querySelector('[data-section="1"] .accordion-body').classList.add('open');
      document.querySelector('[data-section="1"] .accordion-header').classList.add('open');
      updateWizardSteps(1);
    }
  }

  // ── Accordion ──
  function toggleSection(header) {
    if (currentMode === 'guided') return; // no manual toggle in guided mode
    const body = header.nextElementSibling;
    const isOpen = body.classList.contains('open');
    if (isOpen) { body.classList.remove('open'); header.classList.remove('open'); }
    else { body.classList.add('open'); header.classList.add('open'); }
  }

  // ── Wizard Navigation ──
  function updateWizardSteps(step) {
    currentStep = step;
    document.querySelectorAll('.wizard-step').forEach(el => {
      const s = parseInt(el.dataset.step);
      el.classList.remove('active', 'done', 'pending');
      if (s === step) el.classList.add('active');
      else if (s < step) el.classList.add('done');
      else el.classList.add('pending');
    });
    // open target section, close others
    document.querySelectorAll('.accordion-body').forEach((b, i) => {
      const isTarget = (i + 1) === step;
      b.classList.toggle('open', isTarget);
      b.previousElementSibling.classList.toggle('open', isTarget);
    });
  }

  function goToStep(step) { if (currentMode === 'guided') updateWizardSteps(step); }
  function nextStep(from) { if (currentMode === 'guided') updateWizardSteps(Math.min(from + 1, 4)); }
  function prevStep(from) { if (currentMode === 'guided') updateWizardSteps(Math.max(from - 1, 1)); }

  // ── Pipeline-Creative Coupling ──
  const PIPELINE_FIELD_MAP = {
    'full_multimodal': ['field-image-size', 'field-video-size', 'field-video-duration'],
    'video_only': ['field-video-size', 'field-video-duration'],
    'copy_image_only': [],
  };

  function refreshPipelineFields() {
    const mode = document.getElementById('pipeline_mode').value;
    const visible = PIPELINE_FIELD_MAP[mode] || [];
    ['field-image-size', 'field-video-size', 'field-video-duration'].forEach(id => {
      document.getElementById(id).style.display = visible.includes(id) ? 'block' : 'none';
    });
    refreshModeHint();
  }

  function refreshModeHint() {
    const mode = document.getElementById('pipeline_mode').value;
    const summaryEl = document.getElementById('mode-summary');
    const summaries = {
      'full_multimodal': 'Mode: image + video generation. All creative spec fields shown.',
      'video_only': 'Mode: video-only pipeline. Image size hidden.',
      'copy_image_only': 'Mode: image-only pipeline. Video fields hidden.',
    };
    summaryEl.textContent = summaries[mode] || 'Loading pipeline modes...';
  }

  // ── Quick Fill Creative Specs ──
  function buildQuickFillOptions() {
    const sel = document.getElementById('quick-fill-preset');
    sel.innerHTML = '<option value="">Quick Fill...</option>';
    // Recent (auto) — stored in localStorage
    const recent = JSON.parse(localStorage.getItem('crispy_recent_specs') || '[]');
    if (recent.length) {
      sel.appendChild(createOptgroup('Recent (auto)', recent.map((s, i) => ({
        value: 'recent_' + i,
        label: s.image_size + ' / ' + s.video_size + ' / ' + s.resolution + ' / ' + s.video_duration_seconds + 's',
        spec: s,
      }))));
    }
    // My Presets — fetch from API
    fetch('/creative-presets?workspace_name=' + (document.getElementById('workspace_name').value || 'workspace_demo'))
      .then(r => r.json()).then(data => {
        if (data.user && data.user.length) {
          const group = createOptgroup('My Presets', data.user.map(p => ({
            value: 'user_' + p.id,
            label: p.name + ' · ' + (p.image_size || '?') + ' / ' + (p.video_size || '?') + ' / ' + (p.resolution || '?') + ' / ' + (p.video_duration_seconds || '?') + 's',
            spec: { image_size: p.image_size, video_size: p.video_size, resolution: p.resolution, video_duration_seconds: p.video_duration_seconds, platform_targets: p.platform_targets },
          })));
          sel.appendChild(group);
        }
      });
    // System Defaults
    sel.appendChild(createOptgroup('System Defaults', [
      { value: 'sys_meta_square_5s', label: '1:1 Square 720p 5s', spec: { image_size: '1:1', video_size: '1:1', resolution: '720p', video_duration_seconds: 5 } },
      { value: 'sys_meta_vertical_5s', label: '9:16 Vertical 720p 5s', spec: { image_size: '9:16', video_size: '9:16', resolution: '720p', video_duration_seconds: 5 } },
      { value: 'sys_youtube_landscape_6s', label: '16:9 Landscape 1080p 6s', spec: { image_size: '16:9', video_size: '16:9', resolution: '1080p', video_duration_seconds: 6 } },
      { value: 'sys_marketplace_main_image_pack', label: '1:1 Marketplace 2000px', spec: { image_size: '1:1', video_size: '1:1', resolution: '2000px', video_duration_seconds: 5, marketplace: true } },
    ]));
  }

  function createOptgroup(label, items) {
    const g = document.createElement('optgroup');
    g.label = label;
    items.forEach(item => {
      const opt = document.createElement('option');
      opt.value = item.value;
      opt.textContent = item.label;
      opt._spec = item.spec;
      g.appendChild(opt);
    });
    return g;
  }

  function applyQuickFill() {
    const sel = document.getElementById('quick-fill-preset');
    const opt = sel.selectedOptions[0];
    if (!opt || !opt._spec) return;
    const s = opt._spec;
    document.getElementById('image_size').value = s.image_size || '';
    document.getElementById('video_size').value = s.video_size || '';
    document.getElementById('resolution').value = s.resolution || '';
    document.getElementById('video_duration_seconds').value = s.video_duration_seconds || '';
    document.getElementById('marketplace-fields').style.display = s.marketplace ? 'block' : 'none';
  }

  function saveCurrentAsCreativePreset() {
    const name = prompt('Preset name:');
    if (!name) return;
    const payload = {
      name: name,
      workspace_name: document.getElementById('workspace_name').value || 'workspace_demo',
      image_size: document.getElementById('image_size').value,
      video_size: document.getElementById('video_size').value,
      resolution: document.getElementById('resolution').value,
      video_duration_seconds: parseInt(document.getElementById('video_duration_seconds').value) || 5,
    };
    fetch('/creative-presets', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
      .then(r => { if (!r.ok) return r.text().then(d => { throw new Error(d); }); return r.json(); })
      .then(() => { buildQuickFillOptions(); })
      .catch(e => alert('Error: ' + e.message));
  }

  function manageCreativePresets() {
    alert('Preset management panel coming. For now, use the API directly or delete/recreate.');
    buildQuickFillOptions();
  }

  // ── Product Code Hint ──
  function checkProductHint() {
    const code = document.getElementById('product_code').value.trim();
    if (!code) return;
    fetch('/product-config-hint?product_code=' + encodeURIComponent(code))
      .then(r => r.json()).then(hint => {
        if (!hint) return;
        lastProductConfig = hint;
        const el = document.getElementById('product-hint');
        el.style.display = 'block';
        el.innerHTML = code + ' last used: <b>' + (hint.pipeline_mode || '?') + '</b>, '
          + (hint.creative_specs ? (hint.creative_specs.image_size || '?') + '/' + (hint.creative_specs.resolution || '?') + '/' + (hint.creative_specs.video_duration_seconds || '?') + 's' : '?')
          + ', ' + (hint.channel || '?') + '. '
          + '<button onclick="applyLastConfig()" style="font-size:11px;padding:4px 8px;">Apply</button> '
          + '<button onclick="document.getElementById(\'product-hint\').style.display=\'none\'" style="font-size:11px;padding:4px 8px;">Dismiss</button>';
      });
  }

  function applyLastConfig() {
    if (!lastProductConfig) return;
    document.getElementById('pipeline_mode').value = lastProductConfig.pipeline_mode || 'full_multimodal';
    document.getElementById('approval_mode').value = lastProductConfig.approval_mode || 'manual';
    document.getElementById('channel').value = lastProductConfig.channel || 'meta';
    document.getElementById('objective').value = lastProductConfig.objective || 'conversions';
    if (lastProductConfig.creative_specs) {
      document.getElementById('image_size').value = lastProductConfig.creative_specs.image_size || '';
      document.getElementById('video_size').value = lastProductConfig.creative_specs.video_size || '';
      document.getElementById('resolution').value = lastProductConfig.creative_specs.resolution || '';
      document.getElementById('video_duration_seconds').value = lastProductConfig.creative_specs.video_duration_seconds || '';
    }
    refreshPipelineFields();
    document.getElementById('product-hint').style.display = 'none';
  }

  // ── Template CRUD ──
  function loadTemplates() {
    const ws = document.getElementById('workspace_name').value || 'workspace_demo';
    fetch('/run-templates?workspace_name=' + encodeURIComponent(ws))
      .then(r => r.json()).then(templates => {
        const sel = document.getElementById('template-selector');
        sel.innerHTML = '<option value="">-- choose template --</option>';
        templates.forEach(t => {
          const opt = document.createElement('option');
          opt.value = t.id;
          opt.textContent = t.name;
          opt._config = t.config_json;
          sel.appendChild(opt);
        });
      });
  }

  function loadTemplate() {
    const sel = document.getElementById('template-selector');
    const opt = sel.selectedOptions[0];
    document.getElementById('btn-rename-tpl').disabled = !opt || !opt.value;
    document.getElementById('btn-delete-tpl').disabled = !opt || !opt.value;
  }

  function applyTemplate() {
    const sel = document.getElementById('template-selector');
    const opt = sel.selectedOptions[0];
    if (!opt || !opt._config) return;
    const cfg = opt._config;
    // Apply all fields from template config
    for (const [key, value] of Object.entries(cfg)) {
      const el = document.getElementById(key);
      if (el && el.type !== 'file') {
        if (el.type === 'checkbox') el.checked = !!value;
        else el.value = value;
      }
    }
    refreshPipelineFields();
    buildQuickFillOptions();
  }

  function saveAsTemplate() {
    const name = prompt('Template name:');
    if (!name) return;
    const config = collectFormConfig();
    fetch('/run-templates', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: name,
        workspace_name: document.getElementById('workspace_name').value || 'workspace_demo',
        config_json: config,
      }),
    })
      .then(r => { if (!r.ok) return r.text().then(d => { throw new Error(d); }); return r.json(); })
      .then(() => loadTemplates())
      .catch(e => alert('Error: ' + e.message));
  }

  function renameTemplate() {
    const sel = document.getElementById('template-selector');
    const id = sel.value;
    if (!id) return;
    const newName = prompt('New name:', sel.selectedOptions[0].textContent);
    if (!newName) return;
    fetch('/run-templates/' + id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: newName }) })
      .then(r => { if (!r.ok) return r.text().then(d => { throw new Error(d); }); return r.json(); })
      .then(() => loadTemplates())
      .catch(e => alert('Error: ' + e.message));
  }

  function deleteTemplate() {
    const sel = document.getElementById('template-selector');
    const id = sel.value;
    if (!id) return;
    if (!confirm('Delete template "' + sel.selectedOptions[0].textContent + '"?')) return;
    fetch('/run-templates/' + id, { method: 'DELETE' })
      .then(r => { if (!r.ok) return r.text().then(d => { throw new Error(d); }); loadTemplates(); })
      .catch(e => alert('Error: ' + e.message));
  }

  function collectFormConfig() {
    const fields = [
      'workspace_name', 'project_name', 'product_name', 'product_code', 'industry_code',
      'campaign_name', 'channel', 'objective', 'pipeline_mode', 'approval_mode',
      'variant_count', 'image_size', 'video_size', 'resolution', 'video_duration_seconds',
      'target_audience', 'price_range', 'key_value_props', 'primary_cta', 'campaign_goal',
      'category_tags', 'research_mode', 'manual_research_brief', 'url_references', 'business_context_extra',
    ];
    const config = {};
    fields.forEach(id => {
      const el = document.getElementById(id);
      if (el) config[id] = el.value;
    });
    return config;
  }

  // ── File Upload & Preview ──
  function handleDrop(event) {
    event.preventDefault();
    const files = event.dataTransfer.files;
    document.getElementById('input_files').files = files;
    refreshFilePreviews();
  }

  function refreshFilePreviews() {
    const files = document.getElementById('input_files').files;
    const grid = document.getElementById('file-preview-grid');
    grid.innerHTML = '';
    for (let i = 0; i < Math.min(files.length, 10); i++) {
      const f = files[i];
      const isVideo = f.type.startsWith('video/');
      if (f.type.startsWith('image/')) {
        const img = document.createElement('img');
        img.src = URL.createObjectURL(f);
        img.className = 'file-preview-thumb';
        grid.appendChild(img);
      } else {
        const div = document.createElement('div');
        div.className = 'file-preview-thumb video';
        div.textContent = f.name.substring(0, 4);
        div.title = f.name;
        grid.appendChild(div);
      }
    }
  }

  // ── Form Submit ──
  function buildCreativeSpecsJSON() {
    const imageSize = document.getElementById('image_size').value.trim();
    const videoSize = document.getElementById('video_size').value.trim();
    const resolution = document.getElementById('resolution').value.trim();
    const duration = parseInt(document.getElementById('video_duration_seconds').value) || 5;
    const spec = { image_size: imageSize, video_size: videoSize, resolution, video_duration_seconds: duration };
    const isMarketplace = document.getElementById('marketplace-fields').style.display === 'block';
    if (isMarketplace) {
      spec.asset_goal = 'marketplace_main_image';
      spec.platform_targets = ['tiktok_shop', 'shopify', 'alibaba', 'amazon'].filter(p => document.getElementById('platform_' + p)?.checked);
      spec.export_size_px = 2000;
      spec.background_policy = 'pure_white';
    }
    return spec;
  }

  function submitCreateRun() {
    const msg = document.getElementById('create-msg');
    msg.textContent = 'Creating run...';
    msg.className = 'status-msg';

    const creativeSpecs = buildCreativeSpecsJSON();

    // Track recent usage
    const recent = JSON.parse(localStorage.getItem('crispy_recent_specs') || '[]');
    recent.unshift(creativeSpecs);
    if (recent.length > 5) recent.length = 5;
    localStorage.setItem('crispy_recent_specs', JSON.stringify(recent));

    const fd = new FormData();
    fd.set('workspace_name', document.getElementById('workspace_name').value);
    fd.set('project_name', document.getElementById('project_name').value);
    fd.set('product_name', document.getElementById('product_name').value);
    fd.set('product_code', document.getElementById('product_code').value);
    fd.set('industry_code', document.getElementById('industry_code').value);
    fd.set('campaign_name', document.getElementById('campaign_name').value);
    fd.set('channel', document.getElementById('channel').value);
    fd.set('objective', document.getElementById('objective').value);
    fd.set('pipeline_mode', document.getElementById('pipeline_mode').value);
    fd.set('approval_mode', document.getElementById('approval_mode').value);
    fd.set('variant_count', document.getElementById('variant_count').value);
    fd.set('creative_preset', 'custom');
    fd.set('creative_specs', JSON.stringify(creativeSpecs));
    fd.set('manual_research_brief', document.getElementById('manual_research_brief').value);
    fd.set('url_references', JSON.stringify(
      (document.getElementById('url_references').value || '').split('\\n').filter(Boolean)
    ));
    fd.set('business_context', JSON.stringify(
      (() => { try { return JSON.parse(document.getElementById('business_context_extra').value || '{}'); } catch(e) { return {}; } })()
    ));
    fd.set('category_tags', JSON.stringify(
      (document.getElementById('category_tags').value || '').split(',').map(s => s.trim()).filter(Boolean)
    ));
    fd.set('enable_research', document.getElementById('research_mode').value === 'autonomous_web' ? 'true' : 'false');

    const fileInput = document.getElementById('input_files');
    for (const f of fileInput.files) {
      fd.append('files', f);
    }

    fetch('/runs/rich', { method: 'POST', body: fd })
      .then(r => r.json().then(data => ({ status: r.status, data })))
      .then(({ status, data }) => {
        if (status >= 400) {
          msg.textContent = 'Error: ' + (data.detail || 'unknown');
          msg.style.color = 'var(--danger)';
          return;
        }
        // Show preflight warnings inline if any
        const pf = data._preflight;
        if (pf && pf.checks && pf.checks.some(c => c.severity !== 'ok')) {
          const warns = pf.checks.filter(c => c.severity !== 'ok').map(c => c.message).join('\\n');
          msg.innerHTML = 'Run created (id: <b>' + data.id + '</b>).<br>Preflight notes:<br>' + warns;
          msg.style.color = pf.severity === 'error' ? 'var(--danger)' : '#b8860b';
        } else {
          msg.innerHTML = 'Run created! (id: <b>' + data.id + '</b>)';
          msg.style.color = 'var(--accent)';
        }
        refreshRunList();
      })
      .catch(err => {
        msg.textContent = 'Error: ' + err.message;
        msg.style.color = 'var(--danger)';
      });
  }

  // ── Init ──
  document.addEventListener('DOMContentLoaded', () => {
    switchMode(currentMode);
    buildQuickFillOptions();
    loadTemplates();
    loadPipelineModes();
    refreshPipelineFields();
    refreshResearchHint();
  });
</script>
"""
```

- [ ] **Step 4: Update `app/api/routes.py`** to use the new dashboard module

In `_dashboard_html()`, replace the massive string with:

```python
def _dashboard_html() -> str:
    from app.dashboard.create_run import CREATE_RUN_HTML, CREATE_RUN_JS
    from app.dashboard.layout import render_dashboard
    # JS for other dashboard features (run list, run detail, polling) comes from
    # existing routes.py code — keep those in the final string assembly
    return render_dashboard(CREATE_RUN_HTML, CREATE_RUN_JS + _dashboard_shared_js())
```

Extract the run list, run detail, and polling JS into a helper `_dashboard_shared_js()` function in routes.py (the existing JS minus createRun/buildCreativeSpecs/refreshPresetHint).

- [ ] **Step 5: Verify dashboard renders**

Run: `pytest tests/test_dashboard_assets.py -v --no-header -q`
Expected: existing tests pass

- [ ] **Step 6: Commit**

```bash
git add app/dashboard/ app/api/routes.py
git commit -m "feat: extract dashboard into app/dashboard/ module with progressive accordion UI"
```

---

### Task 12: Remove old JS and clean up

**Files:**
- Modify: `app/api/routes.py` — remove `buildCreativeSpecs()`, `refreshPresetHint()`, and old `createRun()` from the shared JS
- Modify: `app/dashboard/create_run.py` — verify no duplicate functions

- [ ] **Step 1: Remove old functions from shared JS**

In the `_dashboard_shared_js()` function (extracted from original `_dashboard_html()`), remove:
- `buildCreativeSpecs()` (~lines 1195-1227)
- `refreshPresetHint()` (~lines 1228-1251)
- The old `createRun()` function that does preflight-then-create (~lines 2013-2084)
- Any DOM references to removed elements (e.g., `preset-hint` div if removed)

Verify `detectInputKinds()`, `preflightDetail()`, `loadPipelineModes()`, and other utility functions are preserved if still needed by other parts of the dashboard.

- [ ] **Step 2: Verify no JS errors**

Start the app and manually check the browser console at `/dashboard`. Verify no `ReferenceError` or missing element errors.

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -v --no-header -q`
Expected: all tests pass

- [ ] **Step 4: Commit**

```bash
git add app/api/routes.py app/dashboard/create_run.py
git commit -m "refactor: remove old createRun JS, buildCreativeSpecs, refreshPresetHint"
```

---

### Task 13: Final integration test and manual QA checklist

**Files:**
- Modify: `tests/test_dashboard_assets.py` — add new test for accordion structure

- [ ] **Step 1: Add dashboard structure test**

```python
# Append to tests/test_dashboard_assets.py

def test_dashboard_create_run_has_accordion_sections(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.text
    assert "Product & Assets" in html
    assert "Platform & Creative" in html
    assert "Campaign & Targeting" in html
    assert "Research & Context" in html
    assert "quick-fill-preset" in html
    assert "template-selector" in html
    assert "mode-guided" in html
    assert "mode-expert" in html
    assert "file-drop-zone" in html
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/ -v`
Expected: all tests pass

- [ ] **Step 3: Manual QA checklist**

```
[ ] Load /dashboard — page renders without JS errors
[ ] Toggle between Guided and Expert modes
[ ] Guided: click Next/Back through 4 steps
[ ] Expert: expand/collapse accordion sections freely
[ ] Upload image files — previews appear in grid
[ ] Select different pipeline modes — creative fields show/hide correctly
[ ] Quick Fill: select a system default — fields populate
[ ] Quick Fill: save current as preset (+ Save button)
[ ] Quick Fill: select a user preset — fields populate
[ ] Template: save current form as template
[ ] Template: load a saved template — fields populate
[ ] Template: rename a template
[ ] Template: delete a template
[ ] Product code: type existing code — hint appears
[ ] Product code: click Apply — fields populate from last run
[ ] Submit form — run created, preflight warnings shown inline
[ ] Run appears in runs list
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_dashboard_assets.py
git commit -m "test: add accordion structure test and manual QA checklist"
```

---

### Task 14: Final commit — wire up and verify

- [ ] **Step 1: Ensure all imports are correct**

Run: `python -c "from app.main import create_app; app = create_app(); print('App created successfully')"`

- [ ] **Step 2: Run full test suite one final time**

Run: `pytest tests/ -v`
Expected: all tests pass

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat: complete Create Run UI redesign with progressive accordion and template CRUD"
```

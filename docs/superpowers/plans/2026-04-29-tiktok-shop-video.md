# TikTok Shop Video Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-class `tiktok_shop_video` pipeline mode that generates TikTok Shop conversion videos with selectable creative styles, TikTok-specific scripts, preflight checks, dashboard input, and scoring.

**Architecture:** Reuse the existing reviewable video pipeline stages and add TikTok behavior through a new pipeline mode plus `creative_specs`. Keep schema changes additive: `VideoScriptItem` gains an optional `tiktok` block, existing run modes continue to use current behavior, and TikTok scoring is selected only for `pipeline_mode=tiktok_shop_video`.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, SQLAlchemy, server-rendered dashboard HTML/JS, pytest, uv.

---

## File Structure

- Modify `app/orchestrator/state_machine.py`: add `PipelineMode.TIKTOK_SHOP_VIDEO` and map it to the existing video stage sequence.
- Modify `app/schemas/api.py`: extend the `PipelineMode` literal so request/response validation accepts `tiktok_shop_video`.
- Modify `app/schemas/contracts.py`: add typed TikTok script models and optional `VideoScriptItem.tiktok`.
- Modify `app/services/creative_specs.py`: add `tiktok_shop_conversion_12s` system preset and constants for style validation.
- Modify `app/api/routes.py`: expose the new pipeline display name through `GET /pipeline-modes`.
- Modify `app/services/runs.py`: materialize TikTok defaults for the new mode, pass `pipeline_mode` and `creative_specs` into runtime video scripting/evaluation, and force research off for this mode.
- Modify `app/services/capability_preflight.py`: add TikTok style, reference-media, aspect-ratio, and duration checks.
- Modify `app/agents/runtime.py`: generate TikTok script payloads, storyboard/video prompts, and TikTok scoring keys when the new mode is active.
- Modify `app/dashboard/create_run.py`: add the `TikTok Video Style` dropdown near video specs and submit it in `creative_specs`.
- Modify tests in `tests/test_pipeline_api.py`, `tests/test_creative_presets.py`, `tests/test_preflight_inline.py`, `tests/test_rich_run.py`, and `tests/test_dashboard_assets.py`.

## Task 1: Pipeline Mode, API Schema, And Preset

**Files:**
- Modify: `app/orchestrator/state_machine.py`
- Modify: `app/schemas/api.py`
- Modify: `app/services/creative_specs.py`
- Modify: `app/api/routes.py`
- Test: `tests/test_pipeline_api.py`
- Test: `tests/test_creative_presets.py`

- [ ] **Step 1: Write failing pipeline mode and preset tests**

Add these assertions to `tests/test_pipeline_api.py::test_pipeline_modes_endpoint`:

```python
    assert "tiktok_shop_video" in modes
    assert modes["tiktok_shop_video"]["display_name"] == "TikTok Shop Video"
    assert modes["tiktok_shop_video"]["stages"] == stage_plan_for("video_only")
```

Add this test to `tests/test_creative_presets.py`:

```python
def test_tiktok_shop_conversion_preset_is_available(client):
    resp = client.get("/creative-presets?workspace_name=test_ws")
    assert resp.status_code == 200
    system = {p["key"]: p for p in resp.json()["system"]}

    preset = system["tiktok_shop_conversion_12s"]
    assert preset["image_size"] == "9:16"
    assert preset["video_size"] == "9:16"
    assert preset["resolution"] == "720p"
    assert preset["video_duration_seconds"] == 12
    assert preset["platform_targets"] == ["tiktok", "tiktok_shop"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_pipeline_api.py::test_pipeline_modes_endpoint tests/test_creative_presets.py::test_tiktok_shop_conversion_preset_is_available -v
```

Expected: fail because `tiktok_shop_video` and `tiktok_shop_conversion_12s` do not exist yet.

- [ ] **Step 3: Add pipeline mode and API literal**

In `app/orchestrator/state_machine.py`, add:

```python
class PipelineMode(StrEnum):
    COPY_IMAGE_ONLY = "copy_image_only"
    VIDEO_ONLY = "video_only"
    FULL_MULTIMODAL = "full_multimodal"
    MARKETPLACE_MAIN_IMAGE = "marketplace_main_image"
    TIKTOK_SHOP_VIDEO = "tiktok_shop_video"
```

Add the new mode to `PIPELINE_STAGE_PLANS` using the same stages as `VIDEO_ONLY`:

```python
    PipelineMode.TIKTOK_SHOP_VIDEO.value: [
        StageName.INTAKE.value,
        StageName.PLANNING.value,
        StageName.DIVERGENCE.value,
        StageName.VIDEO_SCRIPTING.value,
        StageName.STORYBOARD_IMAGE_GENERATION.value,
        StageName.VIDEO_GENERATION.value,
        StageName.VISUAL_QUALITY_ASSESSMENT.value,
        StageName.EVALUATION_SELECTION.value,
    ],
```

In `app/schemas/api.py`, update the literal:

```python
PipelineMode = Literal[
    "copy_image_only",
    "video_only",
    "full_multimodal",
    "marketplace_main_image",
    "tiktok_shop_video",
]
```

- [ ] **Step 4: Add preset and style constants**

In `app/services/creative_specs.py`, add constants near `CREATIVE_PRESETS`:

```python
TIKTOK_SHOP_VIDEO_STYLES = {"ugc_demo", "direct_response_ad", "shop_account_content"}
TIKTOK_SHOP_VIDEO_DEFAULT_STYLE = "ugc_demo"
TIKTOK_SHOP_VIDEO_PRESET = "tiktok_shop_conversion_12s"
```

Add this preset to `CREATIVE_PRESETS`:

```python
    TIKTOK_SHOP_VIDEO_PRESET: {
        "image_size": "9:16",
        "video_size": "9:16",
        "resolution": "720p",
        "video_duration_seconds": 12,
        "platform": "tiktok",
        "creative_goal": "shop_conversion_video",
        "tiktok_video_style": TIKTOK_SHOP_VIDEO_DEFAULT_STYLE,
        "platform_targets": ["tiktok", "tiktok_shop"],
    },
```

- [ ] **Step 5: Add pipeline display label**

In `app/api/routes.py::_pipeline_mode_views`, add:

```python
        PipelineMode.TIKTOK_SHOP_VIDEO.value: "TikTok Shop Video",
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
uv run pytest tests/test_pipeline_api.py::test_pipeline_modes_endpoint tests/test_creative_presets.py::test_tiktok_shop_conversion_preset_is_available -v
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add app/orchestrator/state_machine.py app/schemas/api.py app/services/creative_specs.py app/api/routes.py tests/test_pipeline_api.py tests/test_creative_presets.py
git commit -m "feat: add TikTok Shop video mode and preset"
```

## Task 2: Run Creation Defaults And Rich Run Compatibility

**Files:**
- Modify: `app/services/runs.py`
- Test: `tests/test_pipeline_api.py`
- Test: `tests/test_rich_run.py`

- [ ] **Step 1: Write failing create-run test**

Add this test to `tests/test_pipeline_api.py`:

```python
def test_pipeline_mode_tiktok_shop_video_materializes_defaults(client):
    create_resp = client.post(
        "/runs",
        json={
            "workspace_name": "w-tiktok",
            "project_name": "p-tiktok",
            "product_name": "pet grooming glove",
            "product_code": "TT-001",
            "industry_code": "pet_care",
            "campaign_name": "tiktok-shop-video",
            "pipeline_mode": "tiktok_shop_video",
            "creative_preset": "custom",
            "creative_specs": {
                "image_size": "9:16",
                "video_size": "9:16",
                "resolution": "720p",
                "video_duration_seconds": 12,
                "tiktok_video_style": "direct_response_ad",
            },
            "enable_research": True,
        },
    )
    assert create_resp.status_code == 200
    run = create_resp.json()
    assert run["pipeline_mode"] == "tiktok_shop_video"
    assert run["creative_preset"] == "tiktok_shop_conversion_12s"
    assert run["creative_specs"]["platform"] == "tiktok"
    assert run["creative_specs"]["creative_goal"] == "shop_conversion_video"
    assert run["creative_specs"]["tiktok_video_style"] == "direct_response_ad"
    assert run["creative_specs"]["platform_targets"] == ["tiktok", "tiktok_shop"]
    assert run["enable_research"] is False
    assert [task["stage_name"] for task in run["stage_tasks"]] == stage_plan_for("tiktok_shop_video")
```

- [ ] **Step 2: Write failing rich-run test**

Add this test to `tests/test_rich_run.py`:

```python
def test_rich_run_accepts_tiktok_shop_video_style(client):
    resp = client.post(
        "/runs/rich",
        data={
            "workspace_name": "tiktok_rich_ws",
            "project_name": "tiktok_rich_project",
            "product_name": "portable blender",
            "product_code": "TT-RICH-001",
            "industry_code": "kitchen",
            "campaign_name": "tiktok-rich",
            "pipeline_mode": "tiktok_shop_video",
            "creative_preset": "tiktok_shop_conversion_12s",
            "creative_specs": '{"video_size":"9:16","video_duration_seconds":12,"tiktok_video_style":"shop_account_content"}',
            "manual_research_brief": "Show daily smoothie prep for busy buyers.",
            "enable_research": "true",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["pipeline_mode"] == "tiktok_shop_video"
    assert body["creative_specs"]["tiktok_video_style"] == "shop_account_content"
    assert body["enable_research"] is False
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_pipeline_api.py::test_pipeline_mode_tiktok_shop_video_materializes_defaults tests/test_rich_run.py::test_rich_run_accepts_tiktok_shop_video_style -v
```

Expected: fail until run creation applies TikTok defaults and disables research for the mode.

- [ ] **Step 4: Add TikTok default materialization**

In `app/services/runs.py`, import constants:

```python
from app.services.creative_specs import (
    TIKTOK_SHOP_VIDEO_DEFAULT_STYLE,
    TIKTOK_SHOP_VIDEO_PRESET,
    resolve_creative_specs,
)
```

Inside `create_run`, after the existing marketplace block, add:

```python
    if payload.pipeline_mode == "tiktok_shop_video":
        creative_preset = TIKTOK_SHOP_VIDEO_PRESET
        defaults = resolve_creative_specs(creative_preset)
        defaults.update(creative_specs)
        defaults["platform"] = "tiktok"
        defaults["creative_goal"] = "shop_conversion_video"
        defaults.setdefault("tiktok_video_style", TIKTOK_SHOP_VIDEO_DEFAULT_STYLE)
        defaults.setdefault("platform_targets", ["tiktok", "tiktok_shop"])
        creative_specs = defaults
```

Set research off before constructing `PipelineRun`:

```python
    enable_research = False if payload.pipeline_mode == "tiktok_shop_video" else payload.enable_research
```

Then use `enable_research=enable_research` in the `PipelineRun(...)` constructor.

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/test_pipeline_api.py::test_pipeline_mode_tiktok_shop_video_materializes_defaults tests/test_rich_run.py::test_rich_run_accepts_tiktok_shop_video_style -v
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add app/services/runs.py tests/test_pipeline_api.py tests/test_rich_run.py
git commit -m "feat: materialize TikTok Shop video runs"
```

## Task 3: Preflight Validation

**Files:**
- Modify: `app/services/capability_preflight.py`
- Test: `tests/test_pipeline_api.py`
- Test: `tests/test_preflight_inline.py`

- [ ] **Step 1: Write failing invalid-style test**

Add this test to `tests/test_pipeline_api.py`:

```python
def test_tiktok_shop_preflight_rejects_invalid_style(client):
    resp = client.post(
        "/runs/preflight",
        json={
            "pipeline_mode": "tiktok_shop_video",
            "has_image_inputs": True,
            "has_video_inputs": False,
            "creative_specs": {
                "video_size": "9:16",
                "video_duration_seconds": 12,
                "tiktok_video_style": "viral_dance",
            },
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is False
    assert payload["severity"] == "error"
    assert "tiktok_shop_video.style" in [row["key"] for row in payload["checks"]]
```

- [ ] **Step 2: Write failing warning test**

Add this test to `tests/test_preflight_inline.py`:

```python
def test_tiktok_shop_preflight_reports_reference_ratio_and_duration_warnings(client):
    resp = client.post(
        "/runs/preflight",
        json={
            "pipeline_mode": "tiktok_shop_video",
            "has_image_inputs": False,
            "has_video_inputs": False,
            "creative_specs": {
                "video_size": "1:1",
                "video_duration_seconds": 30,
                "tiktok_video_style": "ugc_demo",
            },
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    keys = {row["key"]: row for row in payload["checks"]}
    assert keys["tiktok_shop_video.reference_media"]["severity"] == "warn"
    assert keys["tiktok_shop_video.video_size"]["severity"] == "warn"
    assert keys["tiktok_shop_video.duration"]["severity"] == "warn"
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_pipeline_api.py::test_tiktok_shop_preflight_rejects_invalid_style tests/test_preflight_inline.py::test_tiktok_shop_preflight_reports_reference_ratio_and_duration_warnings -v
```

Expected: fail because TikTok preflight checks do not exist yet.

- [ ] **Step 4: Add TikTok preflight checks**

In `app/services/capability_preflight.py`, import styles:

```python
from app.services.creative_specs import TIKTOK_SHOP_VIDEO_DEFAULT_STYLE, TIKTOK_SHOP_VIDEO_STYLES
```

Inside `preflight_run_capabilities`, after `marketplace_goal` is computed and before stage-specific capability checks, add:

```python
    if pipeline_mode == "tiktok_shop_video":
        style = str(creative_specs.get("tiktok_video_style") or TIKTOK_SHOP_VIDEO_DEFAULT_STYLE)
        if style not in TIKTOK_SHOP_VIDEO_STYLES:
            add_check(
                key="tiktok_shop_video.style",
                severity="error",
                message=(
                    "TikTok Video Style must be one of: "
                    + ", ".join(sorted(TIKTOK_SHOP_VIDEO_STYLES))
                ),
                stage_name="video_scripting",
                agent_name="video_script_agent",
            )
        if not (has_image_inputs or has_video_inputs):
            add_check(
                key="tiktok_shop_video.reference_media",
                severity="warn",
                message="TikTok Shop video works best with uploaded product image or video references.",
                stage_name="intake",
                agent_name="gm_orchestrator",
            )
        if str(creative_specs.get("video_size") or "9:16") != "9:16":
            add_check(
                key="tiktok_shop_video.video_size",
                severity="warn",
                message="TikTok Shop video is recommended in 9:16 vertical format.",
                stage_name="video_generation",
                agent_name="video_generation_agent",
            )
        try:
            duration_seconds = int(creative_specs.get("video_duration_seconds") or 12)
        except (TypeError, ValueError):
            duration_seconds = 0
        if duration_seconds < 6 or duration_seconds > 20:
            add_check(
                key="tiktok_shop_video.duration",
                severity="warn",
                message="TikTok Shop conversion videos are recommended between 6 and 20 seconds.",
                stage_name="video_scripting",
                agent_name="video_script_agent",
            )
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/test_pipeline_api.py::test_tiktok_shop_preflight_rejects_invalid_style tests/test_preflight_inline.py::test_tiktok_shop_preflight_reports_reference_ratio_and_duration_warnings -v
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add app/services/capability_preflight.py tests/test_pipeline_api.py tests/test_preflight_inline.py
git commit -m "feat: add TikTok Shop video preflight checks"
```

## Task 4: Runtime TikTok Script Payload And Prompts

**Files:**
- Modify: `app/schemas/contracts.py`
- Modify: `app/services/runs.py`
- Modify: `app/agents/runtime.py`
- Test: `tests/test_pipeline_api.py`

- [ ] **Step 1: Write failing runtime test**

Add this test to `tests/test_pipeline_api.py`:

```python
def test_tiktok_shop_video_scripting_outputs_tiktok_payload(client):
    create_resp = client.post(
        "/runs",
        json={
            "workspace_name": "w-tiktok-script",
            "project_name": "p-tiktok-script",
            "product_name": "travel toiletry bag",
            "product_code": "TT-SCRIPT-001",
            "industry_code": "travel",
            "campaign_name": "tiktok-script",
            "pipeline_mode": "tiktok_shop_video",
            "creative_preset": "tiktok_shop_conversion_12s",
            "creative_specs": {"tiktok_video_style": "ugc_demo"},
            "business_context": {
                "target_audience": "frequent travelers",
                "key_value_props": ["keeps bottles upright", "clear compartments"],
                "primary_cta": "Shop on TikTok",
            },
            "manual_research_brief": "Show a creator packing for a weekend trip.",
        },
    )
    assert create_resp.status_code == 200
    run_id = create_resp.json()["id"]

    for stage in ["intake", "planning", "divergence", "video_scripting"]:
        _run_worker_once()
        run = client.get(f"/runs/{run_id}").json()
        if stage != "video_scripting":
            client.post(f"/runs/{run_id}/advance", json={"notes": "ok"})

    script_task = next(task for task in run["stage_tasks"] if task["stage_name"] == "video_scripting")
    first_script = script_task["output_payload"]["scripts"][0]
    assert first_script["tiktok"]["style"] == "ugc_demo"
    assert first_script["tiktok"]["opening_hook"]
    assert first_script["tiktok"]["on_screen_text"]
    assert first_script["tiktok"]["voiceover_lines"]
    assert first_script["tiktok"]["shot_timing"][0]["intent"] == "thumb_stop"
    assert first_script["tiktok"]["cta"] == "Shop on TikTok"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/test_pipeline_api.py::test_tiktok_shop_video_scripting_outputs_tiktok_payload -v
```

Expected: fail because `VideoScriptItem` and runtime output do not include `tiktok`.

- [ ] **Step 3: Add TikTok script models**

In `app/schemas/contracts.py`, add models before `VideoScriptItem`:

```python
class TikTokShotTiming(BaseModel):
    start: float = 0.0
    end: float = 0.0
    visual: str = ""
    text_overlay: str = ""
    intent: str = "product_demo"


class TikTokScriptDetails(BaseModel):
    style: str = "ugc_demo"
    opening_hook: str = ""
    on_screen_text: list[str] = Field(default_factory=list)
    voiceover_lines: list[str] = Field(default_factory=list)
    shot_timing: list[TikTokShotTiming] = Field(default_factory=list)
    product_proof_points: list[str] = Field(default_factory=list)
    cta: str = ""
    compliance_notes: list[str] = Field(default_factory=list)
```

Update `VideoScriptItem`:

```python
class VideoScriptItem(BaseModel):
    variant_id: str
    hook: str
    script: str
    shot_list: list[str] = Field(default_factory=list)
    tiktok: TikTokScriptDetails | None = None
```

- [ ] **Step 4: Pass pipeline mode and specs into runtime calls**

In `app/services/runs.py`, update both `runtime.run_video_scripting(...)` calls to include:

```python
                creative_specs=task.input_payload.get("creative_specs", {}),
                pipeline_mode=run.pipeline_mode,
```

Update the `runtime.run_evaluation_selection(...)` call in the main stage executor to include:

```python
                creative_specs=task.input_payload.get("creative_specs", {}),
                pipeline_mode=run.pipeline_mode,
```

Regeneration does not need TikTok evaluation, but the regeneration `run_video_scripting` call should also pass `creative_specs` and `pipeline_mode` so regenerated scripts keep the style.

- [ ] **Step 5: Update runtime method signatures**

In `app/agents/runtime.py`, update `run_video_scripting` signature:

```python
        business_context: dict | None = None,
        provider: str,
        model: str,
        creative_specs: dict | None = None,
        pipeline_mode: str | None = None,
        runtime_config: dict | None = None,
```

Inside the method, set:

```python
        creative_specs = creative_specs or {}
        is_tiktok_shop = pipeline_mode == "tiktok_shop_video"
        tiktok_style = str(creative_specs.get("tiktok_video_style") or "ugc_demo")
```

- [ ] **Step 6: Generate TikTok payloads**

Inside the `for item in variant_set.variants:` loop in `run_video_scripting`, before appending the script, build:

```python
            tiktok_payload = None
            if is_tiktok_shop:
                opening_hook = f"POV: your {product_name} solves this in seconds"
                proof_points = [primary_value, item.message][:2]
                if tiktok_style == "direct_response_ad":
                    opening_hook = f"Stop scrolling if you need {primary_value}"
                    cta_intensity = "strong"
                elif tiktok_style == "shop_account_content":
                    opening_hook = f"Packing one small upgrade from our shop: {product_name}"
                    cta_intensity = "soft"
                else:
                    cta_intensity = "medium"
                tiktok_payload = {
                    "style": tiktok_style,
                    "opening_hook": opening_hook,
                    "on_screen_text": [
                        opening_hook,
                        f"Proof: {primary_value}",
                        cta,
                    ],
                    "voiceover_lines": [
                        opening_hook,
                        f"Here is how {product_name} helps with {primary_value}.",
                        f"If this fits your routine, {cta}.",
                    ],
                    "shot_timing": [
                        {
                            "start": 0,
                            "end": 2,
                            "visual": "fast vertical product reveal in a realistic use scene",
                            "text_overlay": opening_hook,
                            "intent": "thumb_stop",
                        },
                        {
                            "start": 2,
                            "end": 8,
                            "visual": "close product demo with the key proof point visible",
                            "text_overlay": f"Proof: {primary_value}",
                            "intent": "proof",
                        },
                        {
                            "start": 8,
                            "end": float(creative_specs.get("video_duration_seconds") or 12),
                            "visual": "product-forward end frame with clear next step",
                            "text_overlay": cta,
                            "intent": "cta",
                        },
                    ],
                    "product_proof_points": proof_points,
                    "cta": cta,
                    "compliance_notes": [
                        "Do not invent certifications, discounts, platform trends, or unsupported performance claims.",
                        f"CTA intensity: {cta_intensity}.",
                    ],
                }
```

Pass it into `VideoScriptItem(..., tiktok=tiktok_payload)`.

- [ ] **Step 7: Add TikTok context to storyboard and video prompts**

In `run_storyboard_image_generation`, read `script.tiktok`:

```python
                tiktok_details = script.tiktok.model_dump() if script.tiktok else {}
                style_line = f"TikTok style: {tiktok_details.get('style')}. Opening hook: {tiktok_details.get('opening_hook')}." if tiktok_details else ""
```

Append `style_line` to `frame_prompt`.

In `run_video_generation`, read `script.tiktok`:

```python
            tiktok_details = script.tiktok.model_dump() if script.tiktok else {}
            tiktok_line = ""
            if tiktok_details:
                tiktok_line = (
                    f"TikTok Shop style={tiktok_details.get('style')}; "
                    f"opening_hook={tiktok_details.get('opening_hook')}; "
                    f"on_screen_text={tiktok_details.get('on_screen_text')}; "
                    f"cta={tiktok_details.get('cta')}. "
                )
```

Append `tiktok_line` to `video_prompt`.

- [ ] **Step 8: Run focused test**

Run:

```bash
uv run pytest tests/test_pipeline_api.py::test_tiktok_shop_video_scripting_outputs_tiktok_payload -v
```

Expected: pass.

- [ ] **Step 9: Commit**

```bash
git add app/schemas/contracts.py app/services/runs.py app/agents/runtime.py tests/test_pipeline_api.py
git commit -m "feat: generate TikTok Shop script details"
```

## Task 5: TikTok Evaluation Scoring

**Files:**
- Modify: `app/agents/runtime.py`
- Test: `tests/test_pipeline_api.py`

- [ ] **Step 1: Write failing evaluation test**

Add this test to `tests/test_pipeline_api.py`:

```python
def test_tiktok_shop_evaluation_includes_tiktok_scores(client):
    create_resp = client.post(
        "/runs",
        json={
            "workspace_name": "w-tiktok-eval",
            "project_name": "p-tiktok-eval",
            "product_name": "desk cable clips",
            "product_code": "TT-EVAL-001",
            "industry_code": "office",
            "campaign_name": "tiktok-eval",
            "pipeline_mode": "tiktok_shop_video",
            "creative_preset": "tiktok_shop_conversion_12s",
            "creative_specs": {"tiktok_video_style": "direct_response_ad"},
            "business_context": {
                "target_audience": "home office workers",
                "key_value_props": ["clean desk setup"],
                "primary_cta": "Shop Now",
            },
        },
    )
    assert create_resp.status_code == 200
    run_id = create_resp.json()["id"]
    for stage in stage_plan_for("tiktok_shop_video"):
        _run_worker_once()
        run = client.get(f"/runs/{run_id}").json()
        if stage != "evaluation_selection":
            client.post(f"/runs/{run_id}/advance", json={"notes": "ok"})

    evaluation_task = next(task for task in run["stage_tasks"] if task["stage_name"] == "evaluation_selection")
    ranked = evaluation_task["output_payload"]["evaluation_result"]["ranked_variants"][0]
    for key in [
        "thumb_stop_power",
        "product_clarity",
        "purchase_intent",
        "native_tiktok_feel",
        "watch_through_potential",
        "claim_safety",
        "generation_feasibility",
    ]:
        assert key in ranked["sub_scores"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/test_pipeline_api.py::test_tiktok_shop_evaluation_includes_tiktok_scores -v
```

Expected: fail because evaluation does not add TikTok-specific score keys.

- [ ] **Step 3: Update evaluation signature**

In `app/agents/runtime.py`, update `run_evaluation_selection` signature:

```python
        visual_quality: dict | None = None,
        *,
        provider: str,
        model: str,
        creative_specs: dict | None = None,
        pipeline_mode: str | None = None,
        runtime_config: dict | None = None,
```

At method start:

```python
        creative_specs = creative_specs or {}
        is_tiktok_shop = pipeline_mode == "tiktok_shop_video"
        tiktok_style = str(creative_specs.get("tiktok_video_style") or "ugc_demo")
```

- [ ] **Step 4: Compute TikTok scores**

Inside the per-variant loop, after `visual_qa_score` and before `ranked.append(...)`, compute:

```python
            tiktok_scores: dict[str, float] = {}
            if is_tiktok_shop:
                script_details = script.tiktok if script else None
                has_tiktok_script = script_details is not None
                on_screen_text_count = len(script_details.on_screen_text) if script_details else 0
                shot_count = len(script_details.shot_timing) if script_details else 0
                thumb_stop_power = min(100.0, hook_strength + (8 if has_tiktok_script else 0))
                product_clarity = min(100.0, generation_fit + (6 if shot_count >= 2 else 0))
                purchase_intent = min(100.0, clarity + (10 if tiktok_style == "direct_response_ad" else 4))
                native_tiktok_feel = min(100.0, ai_naturalness + (8 if tiktok_style in {"ugc_demo", "shop_account_content"} else 2))
                watch_through_potential = min(100.0, 62.0 + shot_count * 6 + on_screen_text_count * 2)
                claim_safety = compliance
                generation_feasibility = generation_fit
                tiktok_scores = {
                    "thumb_stop_power": round(thumb_stop_power, 2),
                    "product_clarity": round(product_clarity, 2),
                    "purchase_intent": round(purchase_intent, 2),
                    "native_tiktok_feel": round(native_tiktok_feel, 2),
                    "watch_through_potential": round(watch_through_potential, 2),
                    "claim_safety": round(claim_safety, 2),
                    "generation_feasibility": round(generation_feasibility, 2),
                }
                if tiktok_style == "direct_response_ad":
                    total = round(
                        thumb_stop_power * 0.18
                        + product_clarity * 0.18
                        + purchase_intent * 0.22
                        + native_tiktok_feel * 0.10
                        + watch_through_potential * 0.10
                        + claim_safety * 0.12
                        + generation_feasibility * 0.10,
                        2,
                    )
                elif tiktok_style == "shop_account_content":
                    total = round(
                        thumb_stop_power * 0.14
                        + product_clarity * 0.14
                        + purchase_intent * 0.12
                        + native_tiktok_feel * 0.20
                        + watch_through_potential * 0.18
                        + claim_safety * 0.12
                        + generation_feasibility * 0.10,
                        2,
                    )
                else:
                    total = round(
                        thumb_stop_power * 0.15
                        + product_clarity * 0.20
                        + purchase_intent * 0.15
                        + native_tiktok_feel * 0.18
                        + watch_through_potential * 0.10
                        + claim_safety * 0.12
                        + generation_feasibility * 0.10,
                        2,
                    )
```

When building `RankedVariant`, merge the keys:

```python
                    sub_scores={
                        "hook_strength": round(hook_strength, 2),
                        "clarity": round(clarity, 2),
                        "generation_fit": round(generation_fit, 2),
                        "visual_qa": round(visual_qa_score, 2),
                        "compliance": round(compliance, 2),
                        "ai_naturalness": round(ai_naturalness, 2),
                        **tiktok_scores,
                    },
```

- [ ] **Step 5: Run focused test**

Run:

```bash
uv run pytest tests/test_pipeline_api.py::test_tiktok_shop_evaluation_includes_tiktok_scores -v
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add app/agents/runtime.py tests/test_pipeline_api.py
git commit -m "feat: score TikTok Shop video variants"
```

## Task 6: Dashboard Create Run UI

**Files:**
- Modify: `app/dashboard/create_run.py`
- Test: `tests/test_dashboard_assets.py`

- [ ] **Step 1: Write failing dashboard test**

Add this test to `tests/test_dashboard_assets.py`:

```python
def test_create_run_dashboard_has_tiktok_video_style_control(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.text
    assert 'id="tiktok_video_style"' in html
    assert "TikTok Video Style" in html
    assert "direct_response_ad" in html
    assert "shop_account_content" in html
    assert "creativeSpecs.tiktok_video_style" in html or "spec.tiktok_video_style" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/test_dashboard_assets.py::test_create_run_dashboard_has_tiktok_video_style_control -v
```

Expected: fail because the dropdown is missing.

- [ ] **Step 3: Add dropdown near video specs**

In `app/dashboard/create_run.py`, inside the `.spec-row` after `Duration (s)`, add:

```html
                        <div class="spec-field" id="field-tiktok-video-style" style="display:none;">
                          <label>TikTok Video Style</label>
                          <select id="tiktok_video_style">
                            <option value="ugc_demo" selected>UGC Demo</option>
                            <option value="direct_response_ad">Direct Response Ad</option>
                            <option value="shop_account_content">Shop Account Content</option>
                          </select>
                        </div>
```

- [ ] **Step 4: Update pipeline field refresh**

In `refreshPipelineFields()`, add logic:

```javascript
    const isTikTokShopVideo = mode === 'tiktok_shop_video';
    document.getElementById('field-tiktok-video-style').style.display = isTikTokShopVideo ? 'block' : 'none';
    if (isTikTokShopVideo) {
      document.getElementById('channel').value = 'tiktok';
      document.getElementById('image_size').value = document.getElementById('image_size').value || '9:16';
      document.getElementById('video_size').value = '9:16';
      document.getElementById('resolution').value = document.getElementById('resolution').value || '720p';
      document.getElementById('video_duration_seconds').value = document.getElementById('video_duration_seconds').value || '12';
    }
```

Do not remove existing marketplace behavior.

- [ ] **Step 5: Submit style in creative specs**

In `buildCreativeSpecsJSON()`, after marketplace handling, add:

```javascript
    if (document.getElementById('pipeline_mode').value === 'tiktok_shop_video') {
      spec.platform = 'tiktok';
      spec.creative_goal = 'shop_conversion_video';
      spec.tiktok_video_style = document.getElementById('tiktok_video_style').value || 'ugc_demo';
      spec.platform_targets = ['tiktok', 'tiktok_shop'];
    }
```

In `submitCreateRun()`, update the preset selection:

```javascript
    const pipelineMode = document.getElementById('pipeline_mode').value;
    fd.set('creative_preset',
      pipelineMode === 'marketplace_main_image'
        ? 'marketplace_main_image_pack'
        : pipelineMode === 'tiktok_shop_video'
          ? 'tiktok_shop_conversion_12s'
          : 'custom'
    );
```

- [ ] **Step 6: Include style in templates and product config restore**

In `collectFormConfig()`, add `'tiktok_video_style'` to the `fields` list.

In `applyLastProductConfig()`, after video duration restore, add:

```javascript
      if (lastProductConfig.creative_specs.tiktok_video_style) {
        document.getElementById('tiktok_video_style').value = lastProductConfig.creative_specs.tiktok_video_style;
      }
```

- [ ] **Step 7: Run focused test**

Run:

```bash
uv run pytest tests/test_dashboard_assets.py::test_create_run_dashboard_has_tiktok_video_style_control -v
```

Expected: pass.

- [ ] **Step 8: Commit**

```bash
git add app/dashboard/create_run.py tests/test_dashboard_assets.py
git commit -m "feat: add TikTok style control to create run"
```

## Task 7: Final Regression

**Files:**
- No new files expected.

- [ ] **Step 1: Run focused TikTok-related tests**

Run:

```bash
uv run pytest \
  tests/test_pipeline_api.py::test_pipeline_modes_endpoint \
  tests/test_pipeline_api.py::test_pipeline_mode_tiktok_shop_video_materializes_defaults \
  tests/test_pipeline_api.py::test_tiktok_shop_preflight_rejects_invalid_style \
  tests/test_pipeline_api.py::test_tiktok_shop_video_scripting_outputs_tiktok_payload \
  tests/test_pipeline_api.py::test_tiktok_shop_evaluation_includes_tiktok_scores \
  tests/test_creative_presets.py::test_tiktok_shop_conversion_preset_is_available \
  tests/test_preflight_inline.py::test_tiktok_shop_preflight_reports_reference_ratio_and_duration_warnings \
  tests/test_rich_run.py::test_rich_run_accepts_tiktok_shop_video_style \
  tests/test_dashboard_assets.py::test_create_run_dashboard_has_tiktok_video_style_control \
  -v
```

Expected: pass.

- [ ] **Step 2: Run broader pipeline and dashboard tests**

Run:

```bash
uv run pytest tests/test_pipeline_api.py tests/test_rich_run.py tests/test_preflight_inline.py tests/test_creative_presets.py tests/test_dashboard_assets.py -v
```

Expected: pass.

- [ ] **Step 3: Inspect final diff**

Run:

```bash
git status --short
git diff --stat HEAD
```

Expected: only intended files changed since the last task commit, or no changes if all task commits were made.

- [ ] **Step 4: Commit any final fixes**

If Step 2 required fixes, commit them:

```bash
git add app tests
git commit -m "test: cover TikTok Shop video pipeline"
```

If there are no remaining changes, skip this commit.

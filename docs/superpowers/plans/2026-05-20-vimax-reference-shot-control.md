# ViMax Reference Bridge & Shot Control — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire historical best images into generation stages, pass storyboard frames into video generation, add structured shot contracts, and enrich QA/evaluation context with shot-plan data.

**Architecture:** Pure additive changes across 4 files. `runs.py` queries DB for historical images and passes them downstream. `runtime.py` methods gain optional parameters. `contracts.py` gets ViMax-style ShotPlanItem models. No new stages, no schema changes, zero additional LLM calls.

**Tech Stack:** Python 3.12+, Pydantic v2, SQLAlchemy, existing Crispy agent runtime

---

## File Map

| File | Responsibility |
|---|---|
| `app/services/runs.py` | DB queries for historical images; dispatch into runtime |
| `app/agents/runtime.py` | Consume historical refs; generate shot plans; enrich QA/eval |
| `app/schemas/contracts.py` | ShotFramePlan, ShotPlanItem models |
| `app/services/feedback.py` | GmMemory content: append reference_image_uri |

---

### Task 1: Add historical best image query helper

**Files:**
- Modify: `app/services/runs.py`

- [ ] **Step 1: Add `_best_historical_reference_images()` function in `runs.py`**

Insert before `_build_task_input()` (line 667):

```python
def _best_historical_reference_images(db: Session, product_code: str, limit: int = 2) -> list[dict]:
    """Return top-scored historical variant images for a product as data URL dicts."""
    from app.data.models import VariantAsset, RunVariant
    rows = (
        db.query(VariantAsset)
        .join(RunVariant, VariantAsset.run_variant_id == RunVariant.id)
        .filter(
            VariantAsset.asset_type == "image",
            VariantAsset.uri.isnot(None),
            RunVariant.current_score.isnot(None),
        )
        .order_by(RunVariant.current_score.desc())
        .limit(limit)
        .all()
    )
    results: list[dict] = []
    for asset in rows:
        path = Path(asset.uri) if asset.uri else None
        if not path or not path.exists() or not path.is_file():
            continue
        raw = path.read_bytes()
        mime = mimetypes.guess_type(str(path))[0] or "image/png"
        encoded = base64.b64encode(raw).decode("ascii")
        data_url = f"data:{mime};base64,{encoded}"
        results.append({
            "uri": data_url,
            "description": "Previously generated winning product image",
            "variant_score": asset.variant.current_score if asset.variant else None,
        })
    return results
```

Also add imports at top of `runs.py`: `import base64`, `import mimetypes`. (`Path` is already imported at line 7.)

- [ ] **Step 2: Verify imports and syntax**

```bash
uv run python -c "from app.services.runs import _best_historical_reference_images; print('ok')"
```

Expected: `ok` (function loads without error).

- [ ] **Step 3: Commit**

```bash
git add app/services/runs.py
git commit -m "feat: add _best_historical_reference_images helper for querying top-scored variant images"
```

---

### Task 2: Extend `_reference_image_inputs()` to accept extra references

**Files:**
- Modify: `app/agents/runtime.py:265-279`

- [ ] **Step 1: Add `extra_references` parameter**

Change method signature and body at line 265:

```python
def _reference_image_inputs(
    self,
    intake: ProductIntake | None,
    extra_references: list[dict] | None = None,
) -> list[str]:
    if not intake:
        return []
    rows = intake.image_references or []
    inputs: list[str] = []
    for row in rows[:2]:
        if not isinstance(row, dict):
            continue
        uri = row.get("uri")
        if not isinstance(uri, str):
            continue
        data_url = self._local_image_to_data_url(uri)
        if data_url:
            inputs.append(data_url)
    # Append historical best images, cap at 4 total
    for ref in (extra_references or [])[:2]:
        data_url = ref.get("uri")
        if isinstance(data_url, str) and data_url:
            if len(inputs) >= 4:
                break
            inputs.append(data_url)
    return inputs
```

- [ ] **Step 2: Commit**

```bash
git add app/agents/runtime.py
git commit -m "feat: extend _reference_image_inputs to accept extra_references with 4-image cap"
```

---

### Task 3: Pass historical references to `run_copy_image_generation()`

**Files:**
- Modify: `app/agents/runtime.py:972` (signature and body)
- Modify: `app/services/runs.py:1370-1382` (call site)

- [ ] **Step 1: Add `historical_references` parameter to `run_copy_image_generation()`**

At line 972, add parameter after `runtime_config`:

```python
def run_copy_image_generation(
    self,
    run_id: str,
    variant_set: VariantSet,
    *,
    intake: ProductIntake | None,
    business_context: dict | None,
    creative_specs: dict | None,
    market: str,
    locale: str,
    provider: str,
    model: str,
    runtime_config: dict | None = None,
    historical_references: list[dict] | None = None,
) -> StageOutput:
```

At line 1013, change the `_reference_image_inputs` call:

```python
reference_inputs = self._reference_image_inputs(intake, extra_references=historical_references)
```

- [ ] **Step 2: Pass historical references from `runs.py` call site**

At line 1370-1382 in `runs.py`, add the query call before dispatching:

```python
historical_refs = _best_historical_reference_images(db, run.product_code, limit=2)
output = runtime.run_copy_image_generation(
    run.id,
    variants,
    intake=intake,
    business_context=task.input_payload.get("business_context", {}),
    creative_specs=task.input_payload.get("creative_specs", {}),
    market=run.market,
    locale=run.locale,
    provider=provider_name,
    model=model_name,
    runtime_config=runtime_config,
    historical_references=historical_refs,
)
```

- [ ] **Step 3: Commit**

```bash
git add app/agents/runtime.py app/services/runs.py
git commit -m "feat: pass historical best images as references into copy image generation"
```

---

### Task 4: Pass historical references to `run_storyboard_image_generation()`

**Files:**
- Modify: `app/agents/runtime.py:1406` (signature)
- Modify: `app/services/runs.py:1414-1420` (call site)

- [ ] **Step 1: Add `historical_references` parameter to `run_storyboard_image_generation()`**

At line 1406, add parameter:

```python
def run_storyboard_image_generation(
    self,
    run_id: str,
    script_pack: VideoScriptPack,
    *,
    provider: str,
    model: str,
    creative_specs: dict | None = None,
    runtime_config: dict | None = None,
    historical_references: list[dict] | None = None,
) -> StageOutput:
```

Inside the method, find where `_generate_image()` is called for each frame (around line 1500-1530). Add the historical references to the `reference_image_urls` parameter. Read the exact frame generation loop first to know the exact location.

- [ ] **Step 2: Pass historical references from `runs.py` call site**

At line 1414-1420 in `runs.py`:

```python
historical_refs = _best_historical_reference_images(db, run.product_code, limit=2)
output = runtime.run_storyboard_image_generation(
    run.id,
    scripts,
    creative_specs=task.input_payload.get("creative_specs", {}),
    provider=provider_name,
    model=model_name,
    runtime_config=storyboard_runtime_config,
    historical_references=historical_refs,
)
```

- [ ] **Step 3: Build frame reference URLs from historical refs**

In `run_storyboard_image_generation()`, before the frame generation loop (around line 1440), convert historical refs to data URLs:

```python
historical_frame_refs: list[str] = []
for ref in (historical_references or [])[:2]:
    data_url = ref.get("uri")
    if isinstance(data_url, str) and data_url:
        historical_frame_refs.append(data_url)
```

- [ ] **Step 4: Inject into `_generate_image()` call at line 1476**

Change the `_generate_image()` call at lines 1476-1482 from:

```python
image_result, image_provider, image_model = self._generate_image(
    fallback_provider=provider,
    fallback_model=model,
    prompt=frame_prompt,
    size=image_size,
    runtime_config=runtime_config,
)
```

To:

```python
image_result, image_provider, image_model = self._generate_image(
    fallback_provider=provider,
    fallback_model=model,
    prompt=frame_prompt,
    size=image_size,
    runtime_config=runtime_config,
    reference_image_urls=historical_frame_refs if historical_frame_refs else None,
)
```

- [ ] **Step 5: Commit**

```bash
git add app/agents/runtime.py app/services/runs.py
git commit -m "feat: pass historical best images into storyboard frame generation"
```

---

### Task 5: Add GmMemory visual reference in feedback import

**Files:**
- Modify: `app/services/feedback.py:215-230`

- [ ] **Step 1: Add `image_uri` to `_variant_pattern_payload()` return dict**

At line 92-104 in `feedback.py`, add `image_uri` field to the return dict:

```python
return {
    "variant_id": variant.variant_id,
    "angle": variant.angle,
    "hook": variant.hook,
    "message": variant.message,
    "visual_pattern": image_payload.get("prompt") if image_asset else None,
    "image_uri": image_asset.uri if image_asset else None,
    "image_role": image_payload.get("image_role") if image_asset else None,
    "marketplace_qa_status": (image_payload.get("marketplace_qa") or {}).get("status") if image_asset else None,
    "platform_readiness": platform_readiness,
    "visual_review_tags": review_tags,
    "copy_pattern": ((copy_asset.payload or {}).get("headline") if copy_asset else None),
    "script_pattern": ((script_asset.payload or {}).get("hook") if script_asset else None),
}
```

The `pattern_payload` (which flows into `GmMemory.content`) now carries `image_uri`. No schema change needed — GmMemory.content is JSON.

- [ ] **Step 2: Commit**

```bash
git add app/services/feedback.py
git commit -m "feat: append reference_image_uri to GmMemory product-scope content"
```

---

### Task 6: Add ShotFramePlan and ShotPlanItem to contracts

**Files:**
- Modify: `app/schemas/contracts.py`
- Create: `tests/test_video_control_contracts.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_video_control_contracts.py`:

```python
import pytest
from app.schemas.contracts import ShotFramePlan, ShotPlanItem, VideoScriptItem


class TestShotContracts:
    def test_shot_frame_plan_defaults(self):
        frame = ShotFramePlan(description="Product close-up shot")
        assert frame.description == "Product close-up shot"
        assert frame.visible_product_elements == []

    def test_shot_plan_item_minimal(self):
        shot = ShotPlanItem(
            shot_id="shot_1",
            variant_id="V1",
            intent="product_proof",
            first_frame=ShotFramePlan(description="Product close-up"),
        )
        assert shot.shot_id == "shot_1"
        assert shot.last_frame is None
        assert shot.motion_description == ""
        assert shot.product_continuity_constraints == []

    def test_shot_plan_item_full(self):
        shot = ShotPlanItem(
            shot_id="shot_2",
            variant_id="V1",
            intent="cta_packshot",
            duration_seconds=2.0,
            first_frame=ShotFramePlan(
                description="Product packshot",
                visible_product_elements=["product", "logo"],
            ),
            last_frame=ShotFramePlan(description="CTA end card"),
            motion_description="Slow zoom out",
            audio_description="Voiceover: Shop Now",
            text_overlay="Limited Time Offer",
            product_continuity_constraints=["color_match", "scale_consistent"],
        )
        assert shot.duration_seconds == 2.0
        assert shot.last_frame.description == "CTA end card"
        assert len(shot.product_continuity_constraints) == 2

    def test_video_script_item_backward_compat(self):
        item = VideoScriptItem(
            variant_id="V1",
            hook="Test hook",
            script="Test script",
            shot_list=["shot 1", "shot 2"],
        )
        assert item.shot_plan == []
        assert len(item.shot_list) == 2

    def test_video_script_item_with_shot_plan(self):
        shot = ShotPlanItem(
            shot_id="s1",
            variant_id="V1",
            intent="thumb_stop",
            first_frame=ShotFramePlan(description="Attention grab"),
        )
        item = VideoScriptItem(
            variant_id="V1",
            hook="Hook",
            script="Script",
            shot_list=["old shot"],
            shot_plan=[shot],
        )
        assert len(item.shot_plan) == 1
        assert item.shot_plan[0].intent == "thumb_stop"
        assert len(item.shot_list) == 1  # backward compat preserved
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
uv run pytest tests/test_video_control_contracts.py -q
```

Expected: FAIL — `ShotFramePlan` and `ShotPlanItem` not defined.

- [ ] **Step 3: Add models to `contracts.py`**

Insert before `VideoScriptItem` (line 232):

```python
class ShotFramePlan(BaseModel):
    """ViMax-style: static frame snapshot for a single shot frame."""
    description: str
    visible_product_elements: list[str] = Field(default_factory=list)


class ShotPlanItem(BaseModel):
    """ViMax-style: first-frame / last-frame / motion triad shot contract."""
    shot_id: str
    variant_id: str
    intent: str  # thumb_stop | product_proof | usage_demo | cta_packshot
    duration_seconds: float | None = None
    first_frame: ShotFramePlan
    last_frame: ShotFramePlan | None = None
    motion_description: str = ""
    audio_description: str = ""
    text_overlay: str = ""
    product_continuity_constraints: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
uv run pytest tests/test_video_control_contracts.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/schemas/contracts.py tests/test_video_control_contracts.py
git commit -m "feat: add ShotFramePlan and ShotPlanItem Pydantic models to contracts"
```

---

### Task 7: Extend VideoScriptItem with shot_plan field

**Files:**
- Modify: `app/schemas/contracts.py:232-237`

- [ ] **Step 1: Add `shot_plan` field**

At line 232, modify `VideoScriptItem`:

```python
class VideoScriptItem(BaseModel):
    variant_id: str
    hook: str
    script: str
    shot_list: list[str] = Field(default_factory=list)
    tiktok: TikTokScriptDetails | None = None
    shot_plan: list[ShotPlanItem] = Field(default_factory=list)
```

- [ ] **Step 2: Run existing tests to confirm no regression**

```bash
uv run pytest tests/test_video_control_contracts.py tests/test_pipeline_api.py -q
```

Expected: PASS (shot_plan defaults to [], existing serialization unchanged).

- [ ] **Step 3: Commit**

```bash
git add app/schemas/contracts.py
git commit -m "feat: add shot_plan field to VideoScriptItem with default empty list"
```

---

### Task 8: Generate shot_plan in LLM path of run_video_scripting()

**Files:**
- Modify: `app/agents/runtime.py:1345-1383`

- [ ] **Step 1: Update LLM prompt to request structured shot plan**

At line 1290-1299, update the `task_instruction` to ask for `shot_plan`:

```python
task_instruction=(
    "Generate video hooks and scripts with the product context. "
    f"product={product_name}, audience={audience}, value_props={value_props}, "
    f"media_summary={media_summary}, variants={variant_set.model_dump()}. "
    f"generation_spec={generation_spec}. "
    "Make every shot filmable, product-specific, and constrained by realistic product handling. "
    "For each variant, also output a structured shot_plan array with 3-4 shot objects. "
    "Each shot must have: shot_id, variant_id, intent (one of: thumb_stop, product_proof, usage_demo, cta_packshot), "
    "first_frame with description and visible_product_elements, "
    "optional last_frame, motion_description, audio_description, text_overlay, "
    "and product_continuity_constraints (e.g. color_match, scale_consistent, material_match)."
),
```

- [ ] **Step 2: Parse shot_plan from LLM response**

In the LLM success path (line 1345-1383), after parsing `entry.get("shot_list", [])`, add:

```python
# Parse shot_plan from LLM response if present
shot_plan_raw = entry.get("shot_plan") or []
shot_plan: list[ShotPlanItem] = []
for sp in shot_plan_raw:
    try:
        ff = sp.get("first_frame", {})
        lf = sp.get("last_frame")
        shot_plan.append(ShotPlanItem(
            shot_id=sp.get("shot_id", f"shot_{len(shot_plan)+1}"),
            variant_id=sp.get("variant_id", entry.get("variant_id", "")),
            intent=sp.get("intent", "product_demo"),
            duration_seconds=sp.get("duration_seconds"),
            first_frame=ShotFramePlan(
                description=ff.get("description", ""),
                visible_product_elements=ff.get("visible_product_elements", []),
            ),
            last_frame=ShotFramePlan(
                description=lf.get("description", ""),
                visible_product_elements=lf.get("visible_product_elements", []),
            ) if lf else None,
            motion_description=sp.get("motion_description", ""),
            audio_description=sp.get("audio_description", ""),
            text_overlay=sp.get("text_overlay", ""),
            product_continuity_constraints=sp.get("product_continuity_constraints", []),
        ))
    except Exception:
        continue
```

Then update the `VideoScriptItem(...)` constructor call at line 1375 to include `shot_plan=shot_plan`.

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/test_video_control_contracts.py -q
```

- [ ] **Step 4: Commit**

```bash
git add app/agents/runtime.py
git commit -m "feat: generate structured shot_plan from LLM in video scripting"
```

---

### Task 9: Generate shot_plan in template fallback path

**Files:**
- Modify: `app/agents/runtime.py:1307-1344`

- [ ] **Step 1: Add template-derived shot_plan in fallback**

In the template fallback path (line 1307-1344), after constructing `shot_list`, derive a minimal `shot_plan`:

```python
# Derive minimal shot_plan from shot_list in template fallback
intents = ["thumb_stop", "product_proof", "usage_demo", "cta_packshot"]
fallback_shot_plan: list[ShotPlanItem] = []
for i, shot_text in enumerate(shot_list):
    intent = intents[i] if i < len(intents) else "product_demo"
    fallback_shot_plan.append(ShotPlanItem(
        shot_id=f"shot_{i+1}",
        variant_id=item.variant_id,
        intent=intent,
        first_frame=ShotFramePlan(
            description=shot_text,
            visible_product_elements=[product_name],
        ),
    ))
```

Then pass `shot_plan=fallback_shot_plan` to the `VideoScriptItem(...)` constructor.

Also update the LLM path fallback for the non-TikTok branch.

Import `ShotPlanItem` and `ShotFramePlan` at the top of `runtime.py` if not already imported:
```python
from app.schemas.contracts import (
    ...,
    ShotFramePlan,
    ShotPlanItem,
)
```

- [ ] **Step 2: Run tests**

```bash
uv run pytest tests/test_video_control_contracts.py -q
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add app/agents/runtime.py
git commit -m "feat: derive minimal shot_plan from shot_list in template fallback"
```

---

### Task 10: Feed shot plan context into visual QA

**Files:**
- Modify: `app/agents/runtime.py:1716-1900` (run_visual_quality_assessment)

- [ ] **Step 1: Extract shot_plan from video_scripts**

After line 1757 (`scripts_by_variant = ...`), add extraction:

```python
# Extract shot_plan summaries for QA context
shot_plan_by_variant: dict[str, list[dict]] = {}
for item in _asset_items(video_scripts, "scripts"):
    vid = item.get("variant_id")
    sp = item.get("shot_plan") or []
    if vid and sp:
        shot_plan_by_variant[vid] = [
            {
                "shot_id": s.get("shot_id", ""),
                "intent": s.get("intent", ""),
                "duration": s.get("duration_seconds"),
                "constraints": s.get("product_continuity_constraints", []),
            }
            for s in sp
        ]
```

- [ ] **Step 2: Add shot-plan adherence checks to QA prompt**

Find the QA model prompt composition (around line 1800-1900) and inject `shot_plan_by_variant` into the assessment context:

```python
qa_context_extra = ""
if shot_plan_by_variant:
    qa_context_extra = f"\nShot plan contracts for reference: {json.dumps(shot_plan_by_variant, indent=2)}"
    qa_context_extra += (
        "\nAdditional checks: verify product appears clearly in early frames per shot intent, "
        "visual continuity matches product_continuity_constraints (color, material, scale), "
        "and each frame adheres to its shot intent."
    )
```

Append `qa_context_extra` to the existing QA prompt.

- [ ] **Step 3: Commit**

```bash
git add app/agents/runtime.py
git commit -m "feat: inject shot plan contracts into visual QA assessment prompt"
```

---

### Task 11: Feed shot plan summary into evaluation context

**Files:**
- Modify: `app/agents/runtime.py:1998-2055` (_build_evaluation_context)

- [ ] **Step 1: Add shot_plan_summary to each variant entry**

In `_build_evaluation_context()`, after line 2042 (inside the `entry` dict construction), add:

```python
"shot_plan_summary": [
    {
        "shot_id": s.shot_id,
        "intent": s.intent,
        "duration": s.duration_seconds,
        "constraints": s.product_continuity_constraints,
    }
    for s in script.shot_plan
] if script and script.shot_plan else [],
```

- [ ] **Step 2: Run full test suite to verify no regressions**

```bash
uv run pytest tests/test_video_control_contracts.py tests/test_pipeline_api.py tests/test_rich_run.py -q
```

Expected: PASS.

- [ ] **Step 3: Run broader tests**

```bash
uv run pytest tests/ -q
```

- [ ] **Step 4: Commit**

```bash
git add app/agents/runtime.py
git commit -m "feat: add shot_plan_summary to evaluation context for better scoring"
```

---

## Verification

After all tasks complete, run the full suite:

```bash
uv run pytest tests/ -q
```

Manual checks:
1. Create a run with uploaded product image references — confirm `reference_image_urls` includes historical best images
2. Check `video_scripting` output JSON contains both `shot_list` and `shot_plan`
3. Confirm `visual_quality_assessment` logs reference shot-plan adherence
4. Verify `copy_image_only` and `dtc_site_image` modes still work correctly

# Storyboard-Video Pipeline Fix Design

2026-05-19

## Problem

Three stages in the pipeline call LLMs but discard their outputs, falling back to template string concatenation. Storyboard frames are generated but never passed to video generation as visual reference.

### Current broken flow

```
VideoScriptAgent ──LLM(discard)──> template-built scripts
                                       │
StoryboardAgent ──LLM(discard)──> template-built frame_prompts → image gen
                                       │
VideoGenAgent   ──LLM(discard)──> template-built video_prompt → video gen
                                       ↑
                              storyboard frames never fed
```

### Root cause locations

| Stage | File | Line | Issue |
|-------|------|------|-------|
| Video Script Agent | `runtime.py` | 1204 | `_, model_used, cost = self._chat_complete(...)` |
| Storyboard Agent | `runtime.py` | 1336 | `_, model_used, cost = self._chat_complete(...)` |
| Video Generation | `runtime.py` | 1450 | `_, text_model_used, cost = self._chat_complete(...)` |
| Pipeline orchestration | `runs.py` | 1447 | `run_video_generation()` receives `VideoScriptPack` only, no storyboards |

### Capabilities already exist but are unused

- `_generate_video` accepts `image_urls` via `VideoGenRequest` (line 228)
- `_local_image_to_data_url` converts local images to data URLs (line 239)
- Stage markdown files (`05_video_script_agent.md`, `06_storyboard_agent.md`, `07_video_generation_agent.md`) define structured outputs that match the original design intent

## Target flow

```
VideoScriptAgent ──LLM──> JSON parsed ──> scripts (hook, shots, continuity_risks)
                                            │
StoryboardAgent ──LLM──> JSON parsed ──> frame_prompts → image gen
                                            │
                               frames (image_urls) ──────┐
                                                          ▼
VideoGenAgent   ──LLM──> JSON parsed ──> video_prompt → video gen
```

## Changes

### 1. LLM output wiring (runtime.py)

All three `run_*` methods parse LLM response as structured JSON. On parse failure, fall back to existing template logic.

#### 1a. Video Script Agent (`run_video_scripting`, ~line 1204)

LLM returns:
```json
{
  "scripts": [
    {
      "variant_id": "V1",
      "hook": "...",
      "script": "...",
      "shot_list": ["...", "..."],
      "product_handling": ["..."],
      "continuity_risks": ["..."],
      "cta": "..."
    }
  ]
}
```

Parse result populates the `scripts` list. On failure, fall back to the existing template loop (lines 1206-1224).

#### 1b. Storyboard Agent (`run_storyboard_image_generation`, ~line 1336)

LLM returns:
```json
{
  "frames": [
    {
      "frame_id": "V1_F1",
      "variant_id": "V1",
      "prompt": "...",
      "product_visibility": "...",
      "continuity_constraints": "...",
      "qa_notes": "..."
    }
  ]
}
```

`frame_prompt` uses LLM's `prompt` field instead of the f-string template (lines 1352-1358). On failure, fall back to existing template.

#### 1c. Video Generation Agent (`run_video_generation`, ~line 1450)

LLM returns:
```json
{
  "video_prompts": [
    {
      "variant_id": "V1",
      "prompt": "...",
      "quality_constraints": ["..."]
    }
  ]
}
```

`video_prompt` uses LLM's `prompt` field instead of the f-string template (lines 1464-1470). On failure, fall back to existing template.

#### Fallback protocol

```
LLM response → JSON parse success? → use LLM output
                    ↓ failure
              existing template logic (pipeline does not break)
```

Parse failures append `:fallback_to_template` to `model_used` for observability.

A shared helper `_parse_llm_json(response_text, schema_key)` handles JSON extraction (strip markdown code fences), `json.loads`, and field validation. Each caller provides the expected top-level key.

### 2. Storyboard → video image_urls injection (runtime.py)

`run_video_generation` gains a new parameter `storyboard_frames: list[dict] | None`.

After `generation_spec` is built (~line 1444), inject frame image URLs:

```python
if storyboard_frames:
    frame_urls = []
    for frame in storyboard_frames:
        data_url = self._local_image_to_data_url(frame["image_uri"])
        if data_url:
            frame_urls.append(data_url)
    if frame_urls:
        existing = list(generation_spec.get("image_urls") or [])
        generation_spec["image_urls"] = existing + frame_urls
```

Frames are per-variant: each variant's video call receives its 3 storyboard frames as visual reference.

### 3. Pipeline orchestration (runs.py)

#### 3a. Helper: `_get_stage_output`

```python
def _get_stage_output(db, run_id: str, stage_name: str) -> dict | None:
    """Read the output_payload of the most recent completed task for a stage."""
    task = (
        db.query(StageTask)
        .filter_by(run_id=run_id, stage_name=stage_name, failure_category=None)
        .order_by(StageTask.completed_at.desc())
        .first()
    )
    return task.output_payload if task else None
```

#### 3b. Main pipeline (~line 1407)

In the `video_generation` branch, read storyboard output before calling `run_video_generation`:

```python
elif task.stage_name == "video_generation":
    scripts = VideoScriptPack.model_validate(task.input_payload["video_scripts"])
    storyboard_output = _get_stage_output(db, run.id, "storyboard_image_generation")
    storyboard_frames = (storyboard_output or {}).get("frames", [])
    variant_ids = {s.variant_id for s in scripts.scripts}
    variant_frames = [f for f in storyboard_frames if f.get("variant_id") in variant_ids]

    output = runtime.run_video_generation(
        run.id,
        scripts,
        storyboard_frames=variant_frames,
        ...
    )
```

#### 3c. Single-variant regeneration (~line 2268)

Same pattern for single-variant replay path:

```python
elif stage_name == "video_generation":
    storyboard_output = _get_stage_output(db, run_id, "storyboard_image_generation")
    storyboard_frames = (storyboard_output or {}).get("frames", [])
    variant_frames = [f for f in storyboard_frames if f.get("variant_id") == variant_id]

    output = runtime.run_video_generation(
        run.id,
        _single_script_pack(db, run_id, variant_id),
        storyboard_frames=variant_frames,
        ...
    )
```

### Degradation behavior

| Scenario | Behavior |
|----------|----------|
| `storyboard_frames=None` | No image_urls injected, behavior = current |
| Frame file missing | `_local_image_to_data_url` returns None, frame skipped |
| No storyboard stage ran before video | `_get_stage_output` returns None, storyboard_frames = [] |
| Video model ignores image_urls | Model-side tolerance, empty list already handled |

## Scope

### In scope
- Wire 3 LLM call outputs into downstream stage inputs
- Pass storyboard frame image URLs to video generation API
- Add pipeline orchestration to connect storyboard → video stages
- Fallback to existing template logic on any parse failure

### Out of scope
- Changing `_generate_image` internals (only prompt source changes)
- Changing `VideoGenRequest`, `VideoScriptPack`, or other data models
- Adding new LLM provider or model configurations
- Modifying stage markdown files (already aligned with design)
- Storyboard image QA quality improvements

## Testing

- **Unit**: JSON parse helpers — valid, invalid JSON, missing fields, empty input
- **Integration**: `run_video_generation` with `storyboard_frames` → `generation_spec["image_urls"]` populated correctly
- **Regression**: `storyboard_frames=None` → behavior identical to current
- **Manual**: Full pipeline run, verify each stage consumes upstream LLM output, verify storyboard frames appear as image_urls in VideoGenRequest

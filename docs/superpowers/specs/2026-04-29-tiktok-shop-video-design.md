# TikTok Shop Video Pipeline Design

## Summary

Add a first-class `tiktok_shop_video` pipeline mode for TikTok Shop and store-account product conversion videos. The mode serves small and mid-sized cross-border ecommerce teams that need reviewable, product-forward TikTok assets from uploaded product media, SKU data, and a manual operator brief.

The first version reuses the existing video stages instead of adding a new hook-review stage or invoking research agents. This keeps the MVP trial scope controlled while making TikTok Shop runs visible in APIs, dashboard filters, preflight, artifacts, and future reporting.

## Goals

- Support TikTok Shop conversion video creation as a formal pipeline mode.
- Generate TikTok-native hooks, scripts, shot plans, storyboard prompts, and video prompts from product inputs and manual brief.
- Let operators choose the TikTok creative style from the Create Run UI near the video specs.
- Score TikTok runs with conversion-oriented TikTok dimensions instead of only the generic ad score.
- Preserve the existing human gate flow and video-generation provider preflight checks.

## Non-Goals

- No automatic TikTok trend, competitor, or category research in the first version.
- No new stage such as `hook_generation` or `hook_review`.
- No TikTok publishing API integration.
- No automated TikTok Shop or ads performance import beyond the existing feedback path.
- No dedicated cover-image generation or localization workflow.

## Pipeline Mode

Add:

```yaml
pipeline_mode: tiktok_shop_video
```

Stage plan:

```text
intake
-> planning
-> divergence
-> video_scripting
-> storyboard_image_generation
-> video_generation
-> visual_quality_assessment
-> evaluation_selection
```

The mode should be returned by `GET /pipeline-modes`, accepted by `POST /runs`, `POST /runs/rich`, and handled by `POST /runs/preflight`.

## Default Preset And Specs

Add a system preset:

```yaml
creative_preset: tiktok_shop_conversion_12s
creative_specs:
  platform: tiktok
  creative_goal: shop_conversion_video
  tiktok_video_style: ugc_demo
  image_size: "9:16"
  video_size: "9:16"
  resolution: "720p"
  video_duration_seconds: 12
  platform_targets:
    - tiktok
    - tiktok_shop
```

Supported `creative_specs.tiktok_video_style` values:

```text
ugc_demo
direct_response_ad
shop_account_content
```

Style meanings:

- `ugc_demo`: creator-like product demonstration. Prioritize naturalness, trust, clear use, and product proof.
- `direct_response_ad`: performance ad. Prioritize fast problem-solution framing, dense benefits, offer clarity, and stronger CTA.
- `shop_account_content`: store-account organic content. Prioritize native TikTok feel, watch-through potential, softer CTA, and brand consistency.

## Dashboard UI

In Create Run, show a `TikTok Video Style` dropdown when `pipeline_mode=tiktok_shop_video`.

Placement:

- Put it in the same creative-spec area as `Video Size`, `Resolution`, and `Duration`.
- Do not hide it in advanced JSON or business context fields.

Options:

```text
UGC Demo -> ugc_demo
Direct Response Ad -> direct_response_ad
Shop Account Content -> shop_account_content
```

Default behavior:

- Selecting `tiktok_shop_video` defaults `creative_preset` to `tiktok_shop_conversion_12s`.
- Default `Video Size` to `9:16`.
- Default `Duration` to `12`.
- Keep the specs editable so operators can adjust trial constraints.
- Submit the dropdown value as `creative_specs.tiktok_video_style`.

Manual brief copy can be adjusted for this mode to invite product selling points, target buyer, offer, usage scene, and forbidden claims. The first version should not invoke research behavior for this mode; the manual brief, SKU data, business context, and uploaded media are the source of truth.

## Stage Behavior

### Intake

Reuse existing SKU, image, and video intake behavior. Uploaded media summaries continue to populate `ProductIntake.asset_media_summary`.

For TikTok Shop runs, downstream stages should treat `manual_research_brief`, SKU facts, `business_context`, and `asset_media_summary` as the primary evidence. If reference media is absent, the run can continue with a preflight warning.

### Planning

For `tiktok_shop_video`, planning should summarize:

- buyer problem and purchase trigger,
- most credible product proof points,
- TikTok Shop constraints and claim risks,
- recommended creative style and CTA intensity,
- product details that must remain visually accurate.

### Divergence

For `tiktok_shop_video`, divergence should produce variants with distinct purchase-motivation hypotheses and hook angles. Variants should avoid overlapping hook logic.

Examples of allowed hook logic:

- pain-point demo,
- before-after use case without unsupported claims,
- POV scenario,
- creator testimonial framing,
- product proof close-up,
- offer or bundle urgency for direct response.

### Video Scripting

Keep the existing `VideoScriptItem` fields for compatibility:

```yaml
variant_id
hook
script
shot_list
```

For TikTok Shop runs, add a structured TikTok block to each script payload:

```yaml
tiktok:
  style: ugc_demo | direct_response_ad | shop_account_content
  opening_hook: str
  on_screen_text: list[str]
  voiceover_lines: list[str]
  shot_timing:
    - start: 0
      end: 2
      visual: str
      text_overlay: str
      intent: thumb_stop | proof | product_demo | offer | cta
  product_proof_points: list[str]
  cta: str
  compliance_notes: list[str]
```

The script should be filmable, product-specific, and constrained by uploaded product facts. It should not invent claims, certifications, discounts, or TikTok trends not present in the brief or product context.

### Storyboard Image Generation

For TikTok Shop runs, storyboard prompts should use vertical TikTok product-video composition and reflect the selected style:

- `ugc_demo`: handheld or creator-demo framing, natural product handling, realistic environment.
- `direct_response_ad`: fast product reveal, benefit proof shots, CTA end frame.
- `shop_account_content`: native store-account content, lighter selling pressure, repeatable content format.

Prompts should keep product visibility and physical continuity explicit.

### Video Generation

For TikTok Shop runs, video prompts should include:

- 9:16 target unless operator overrides it,
- target duration from creative specs,
- selected TikTok style,
- product proof points,
- CTA intensity,
- claim-safety and product-continuity constraints.

Provider task metadata and pending async behavior remain unchanged.

### Visual Quality Assessment

Visual QA should include TikTok-specific checks for:

- product clearly visible early,
- vertical composition,
- no broken product continuity,
- no misleading or unsupported visual claim,
- generated asset is not empty, pending, placeholder, or malformed.

The existing local and model-assisted visual QA flow can be reused.

### Evaluation Selection

For `tiktok_shop_video`, add TikTok-specific scoring keys:

```yaml
thumb_stop_power
product_clarity
purchase_intent
native_tiktok_feel
watch_through_potential
claim_safety
generation_feasibility
```

Suggested weighting by style:

```yaml
ugc_demo:
  thumb_stop_power: medium
  product_clarity: high
  purchase_intent: medium
  native_tiktok_feel: high
  watch_through_potential: medium
  claim_safety: high
  generation_feasibility: high

direct_response_ad:
  thumb_stop_power: high
  product_clarity: high
  purchase_intent: high
  native_tiktok_feel: medium
  watch_through_potential: medium
  claim_safety: high
  generation_feasibility: high

shop_account_content:
  thumb_stop_power: medium
  product_clarity: medium
  purchase_intent: medium
  native_tiktok_feel: high
  watch_through_potential: high
  claim_safety: high
  generation_feasibility: high
```

The output should keep existing `RankedVariant` compatibility while including these keys in `sub_scores`.

## Preflight

For `pipeline_mode=tiktok_shop_video`, preflight should:

- require video-generation capability checks because the mode always reaches `video_generation`;
- return `error` for invalid `creative_specs.tiktok_video_style`;
- return `warn` if no image or video references are provided;
- return `warn` if `video_size` is not `9:16`;
- return `warn` if duration is outside the recommended 6-20 second range;
- continue to use configured agent model routing and API key checks.

Warnings should allow manual continuation. Errors should block Create Run submission.

## Data And Compatibility

No database migration is required for the first version because `creative_specs` already stores JSON-compatible data. The new fields are additive.

Existing runs remain valid. Existing `video_only` and `full_multimodal` modes continue to use the current generic scoring unless their specs explicitly opt into TikTok behavior in future work.

Extend `VideoScriptItem` with an optional `tiktok` field. Existing scripts remain valid because the field is optional, and TikTok Shop scripts get a typed place for style, overlay text, voiceover lines, shot timing, proof points, CTA, and compliance notes.

## Test Scope

Add or update tests for:

- `stage_plan_for("tiktok_shop_video")` returns the existing video stage sequence.
- `GET /pipeline-modes` includes `tiktok_shop_video`.
- `POST /runs` accepts `tiktok_shop_video` and materializes TikTok preset specs.
- `POST /runs/rich` accepts media uploads with `tiktok_shop_video`.
- `POST /runs/preflight` reports style errors and TikTok warnings correctly.
- dashboard Create Run includes `TikTok Video Style` near video specs and submits it in `creative_specs`.
- `video_scripting` includes TikTok payload fields for TikTok Shop runs.
- `evaluation_selection` includes TikTok scoring keys for TikTok Shop runs.

## Rollout Notes

This design intentionally makes TikTok Shop video a formal pipeline mode while reusing the existing reviewable state machine. If trial usage proves that operators need to approve hooks before spending video-generation cost, the next version can add a dedicated hook-review stage without changing the first version's run identity or saved creative specs.

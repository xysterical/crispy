# Create Run UI Redesign

**Status**: approved · **Date**: 2026-04-28

## Goal

Redesign the Create Run form to reduce cognitive overload (currently 32 fields in a flat layout) while preserving all functionality. Target users: small cross-border e-commerce operations teams, MVP stage.

## Core Pattern: Progressive Accordion

A single component with two modes of interaction sharing the same DOM:

- **Guided Mode**: Left sidebar step progress indicator + Next/Back buttons. New users follow steps in order, seeing 5-10 fields at a time.
- **Expert Mode**: All accordion panels expandable/collapsible freely. Experienced users can fill or edit any section out of order.
- **Mode toggle**: A single click switches between modes. Preference is remembered per browser (localStorage).

## Field Grouping (4 Sections)

### 1. Product & Assets (expanded by default)

File upload area at the top — the creative starting point. Thumbnail preview grid for uploaded images/videos.
Identity fields below: product_code (required), product_name, workspace_name, project_name, campaign_name, industry_code.

- Upload: drag-and-drop or browse, max 10 files, 50MB each, 200MB total
- Previews: image thumbnails (60x60), video thumbnails with play icon overlay
- Product code acts as the unique ID for cross-run tracking and strategy feedback

### 2. Platform & Creative (expanded by default)

Pipeline mode, approval mode, variant count, creative specs, channel.

**Pipeline-creative coupling**: The visible creative spec fields adapt to pipeline mode:
- `full_multimodal`: image_size, video_size, resolution, video_duration_seconds (all 4)
- `video_only`: video_size, resolution, video_duration_seconds (3, image_size hidden)
- `copy_image_only`: image_size, resolution (2, video fields hidden)

**Creative Specs — Custom-first design**:
- All 4 spec fields are always editable (no disabled state)
- Quick Fill dropdown with 3 sections:
  1. **Recent (auto)**: Last 5 submitted creative spec combinations, auto-recorded
  2. **My Presets**: User-created named presets with full CRUD (create/save, rename, delete)
  3. **System Defaults**: Read-only fallback presets (meta_square, meta_vertical, youtube_landscape, marketplace)
- Marketplace preset no longer forcibly overrides pipeline_mode/approval_mode/variant_count — instead shows advisory hints

### 3. Campaign & Targeting (collapsed by default)

objective, product_description, target_audience, price_range, key_value_props, primary_cta, campaign_goal, category_tags.

### 4. Research & Context (collapsed by default)

research_mode, manual_research_brief, url_references, business_context_extra.

## Template System

### Run Template (global bar, above sections)

- **Load**: Dropdown selector, "Apply" fills all form fields (except file upload)
- **Save Current**: Saves all current non-file field values as a named template
- **Rename**: Inline rename in dropdown or via ⚙ manage panel
- **Delete**: With confirmation dialog

Templates stored as new DB table (`run_templates`). Scoped to workspace. Optional `is_shared` flag for team visibility.

### Creative Preset (within Quick Fill)

- **Save (+ New)**: Saves current creative-spec-only field values as a named preset
- **Rename/Edit/Delete**: Via ⚙ icon next to Quick Fill dropdown
- Stored in `creative_presets` table. Scoped to workspace.

### Relationship

Run Template covers all form fields. Creative Preset covers only creative specs. When a Run Template is loaded, its creative specs are matched against existing Creative Presets — if a match exists, it's highlighted in Quick Fill. They complement each other; neither replaces the other.

## Product Code Intelligence

When product_code is entered and loses focus:
- Look up the most recent run for that product code
- If found, show a subtle hint: "DL-001 last used: full_multimodal, 1:1/1080p/15s, Meta. Apply these settings?"
- One click to auto-fill. Dismissible. Not a blocking dialog.

## Data Flow (Frontend)

### Current state problems
- `buildCreativeSpecs()` duplicates preset definitions from `creative_specs.py`
- `refreshPresetHint()` forcibly overwrites other form fields (pipeline_mode, approval_mode, etc.)
- Preflight check is a separate network round-trip before every create

### Target state
- Preset definitions live only in backend (`creative_specs.py`) — frontend fetches via `GET /creative-specs` (new endpoint)
- `refreshPresetHint()` is removed; marketplace mode shows hints inline, never overwrites
- Pipeline-creative field visibility is computed client-side from pipeline_mode value
- Preflight merges into `/runs/rich`: backend runs preflight internally, returns warnings in the response (single round-trip)

### New/Modified API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/creative-presets` | List all available presets (system + user) with metadata |
| POST | `/creative-presets` | Create a user preset |
| PUT | `/creative-presets/{id}` | Update/rename a user preset |
| DELETE | `/creative-presets/{id}` | Delete a user preset |
| GET | `/run-templates` | List templates for current workspace |
| POST | `/run-templates` | Save current form state as template |
| PUT | `/run-templates/{id}` | Update/rename a template |
| DELETE | `/run-templates/{id}` | Delete a template |
| POST | `/runs/rich` | Modified: runs preflight internally, returns warnings inline |

## Backend Changes

### New models (`app/data/models.py`)
- `CreativePreset`: id, workspace_name, name, image_size, video_size, resolution, video_duration_seconds, platform_targets (JSON), created_at, updated_at
- `RunTemplate`: id, workspace_name, name, config (JSON blob of all form fields), created_at, updated_at

### Modified services
- `creative_specs.py`: add CRUD functions for user presets
- `runs.py`: `create_run()` merges preflight check internally; `get_last_product_config(product_code)` for product code intelligence

### Dashboard HTML
- The `_dashboard_html()` function in `routes.py` needs refactoring. The inline HTML/CSS/JS grows unwieldy at ~1740 lines. Split dashboard rendering into a separate module (`app/dashboard/`) with Jinja2 templates or at minimum separate Python files per section.

## Implementation Order

1. Backend: CreativePreset + RunTemplate models and CRUD endpoints
2. Backend: Merge preflight into `/runs/rich`, add `get_last_product_config`
3. Backend: `GET /creative-presets` with system + user presets
4. Frontend: Refactor `_dashboard_html()` — extract dashboard into `app/dashboard/`
5. Frontend: Progressive Accordion component (HTML + CSS + JS)
6. Frontend: Creative Specs custom-first redesign with pipeline coupling
7. Frontend: Template selector bar with CRUD
8. Frontend: Product code intelligence hint
9. Remove: `buildCreativeSpecs()` JS duplicate, `refreshPresetHint()` side effects
10. Tests: Dashboard HTML structure, creative preset CRUD, template CRUD, pipeline-creative coupling

## Testing

- Unit tests for `CreativePreset` and `RunTemplate` CRUD operations
- Integration tests for `/runs/rich` with inline preflight
- Dashboard HTML snapshot tests for accordion structure
- JS unit tests for pipeline-creative field visibility logic
- Manual QA: guided mode walkthrough, expert mode rapid-fill, template load/save/delete, product code lookup hint

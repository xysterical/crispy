# Crispy Agent Brief (AI-Optimized)

## 0) Snapshot
```yaml
project: crispy
goal: "多产品、多模态广告素材生成 + 人工闸门 + 反馈闭环优化"
status: "MVP可运行（半自动、可审阅、可扩展）"
primary_stack:
  language: "Python 3.11+"
  runtime: "uv"
  api: "FastAPI + Uvicorn"
  orm: "SQLAlchemy"
  schema: "Pydantic"
  db: "SQLite(local) / PostgreSQL-compatible JSON design"
  ui: "FastAPI server-side dashboard pages"
```

## 1) Canonical Pipeline

### 1.1 Pipeline Modes
```yaml
copy_image_only:
  - intake
  - planning
  - divergence
  - copy_image_generation
  - evaluation_selection

video_only:
  - intake
  - planning
  - divergence
  - video_scripting
  - storyboard_image_generation
  - video_generation
  - evaluation_selection

full_multimodal:
  - intake
  - planning
  - divergence
  - copy_image_generation
  - video_scripting
  - storyboard_image_generation
  - video_generation
  - evaluation_selection
```

### 1.2 Stage -> Agent Mapping
```yaml
intake: gm_orchestrator
planning: ideation_agent
divergence: ideation_agent
copy_image_generation: generation_agent
video_scripting: generation_agent
storyboard_image_generation: generation_agent
video_generation: generation_agent
evaluation_selection: scoring_agent
```

### 1.3 Human Gate
```yaml
task_status_flow:
  - draft
  - queued
  - running
  - waiting_review
  - approved | rejected | failed
```

## 2) Multimodal Input and Understanding (Current Behavior)

### 2.1 Input Entry
- `POST /runs/rich` 支持上传：
  - SKU: `.csv`, `.xlsx`
  - Image: `.png`, `.jpg`, `.jpeg`, `.webp`
  - Video: `.mp4`, `.mov`, `.m4v`

### 2.2 Upload Limits
```yaml
max_files: 10
max_single_file: 50MB
max_total: 200MB
```

### 2.3 Intake Media Understanding
- `intake` 阶段会读取上传图片/视频并调用多模态 chat 理解：
  - image -> `image_url`
  - video -> `video_url`
- 产出字段：`ProductIntake.asset_media_summary`
- 若视频理解失败且有图片，会自动降级为“仅图片理解”。

### 2.4 Downstream Consumption
- `copy_image_generation` 使用 `asset_media_summary` + image-focused summary 生成图文素材。
- `video_scripting` 注入 `asset_media_summary`，让 Hook/脚本更贴近真实产品素材。

## 3) Model Routing and API Config

### 3.1 Config Priority
1. per-agent config (`/agent-configs/{agent}`)
2. default config (`agent_name=default`)
3. run payload legacy fields (`model_provider/model_name`, deprecated)

### 3.2 Generation Agent Split Config
```yaml
generation_agent:
  text: top-level provider/model/base_url/api_key_env
  image: extra.image_config
  video: extra.video_config
```

### 3.3 API Key Security
- 仅存储环境变量名，不存明文 key。
- 环境变量自动发现前缀：`CRISPY_API_KEY_`.

## 4) Capability Preflight (Prevent Runtime Surprises)

### 4.1 API
- `POST /runs/preflight`

### 4.2 Input
```json
{
  "pipeline_mode": "copy_image_only | video_only | full_multimodal",
  "has_image_inputs": true,
  "has_video_inputs": false
}
```

### 4.3 Output
```json
{
  "ok": true,
  "severity": "ok | warn | error",
  "summary": "...",
  "checks": [
    {
      "key": "video_generation.video_generation",
      "severity": "error",
      "message": "...",
      "stage_name": "video_generation",
      "agent_name": "generation_agent"
    }
  ]
}
```

### 4.4 Dashboard Behavior
- Create Run 前自动调用 preflight：
  - `error` -> 弹窗并阻止提交
  - `warn` -> 弹确认框，允许人工继续

## 5) Core API Surface

### Run
- `GET /runs`
- `POST /runs`
- `POST /runs/rich`
- `GET /runs/{id}`
- `POST /runs/{id}/advance`
- `POST /runs/{id}/reject`
- `GET /runs/{id}/deliverables`
- `GET /runs/{id}/variants`
- `POST /runs/preflight`

### Config & Persona
- `GET /agent-configs`
- `PATCH /agent-configs/{agent}`
- `GET /agent-configs/env-vars`
- `GET /personas`
- `GET /personas/{agent}`
- `PATCH /personas/{agent}`

### Feedback / Memory
- `POST /feedback/import`
- `GET /projects/{id}/leaderboard`
- `GET /gm-memory`

### UI/Meta
- `GET /pipeline-modes`
- `GET /creative-presets`
- `GET /artifacts`
- `GET /dashboard/*`

## 6) Key Business Fields in Create Run

Required:
```yaml
workspace_name: str
project_name: str
product_name: str
product_code: str       # 全库唯一
industry_code: str
campaign_name: str
creative_preset: str
```

Important optional:
```yaml
pipeline_mode: copy_image_only | video_only | full_multimodal
creative_specs:
  image_size: "1:1 | 9:16 | 16:9 | ..."
  video_size: "1:1 | 9:16 | 16:9 | ..."
  resolution: "480p | 720p | 1080p"
  video_duration_seconds: int
business_context: object
category_tags: string[]
manual_research_brief: str
enable_research: bool (default=false)
```

## 7) Memory System (GM)

Two-layer memory:
```yaml
scope: product | industry
product_key: product_code
industry_key: industry_code
storage: gm_memory.content(JSON)
```

Write path:
- feedback import 后写入 product + industry 两类 memory
- 同步更新 `gm_instruction_version`

Read path:
- planning 阶段注入历史经验（产品优先，再行业补足）

## 8) Data Model Landmarks
- `workspace / project / product / campaign`
- `pipeline_run / stage_task / artifact / scorecard`
- `feedback_import / performance_snapshot`
- `gm_memory / gm_instruction_version`
- `persona_version`

## 9) Practical Compatibility Notes
- 目前是“OpenAI-compatible 优先”架构，非兼容协议需新增 provider 适配。
- 图片理解通常兼容较广；视频理解和视频生成差异更大，建议始终走 preflight。
- 当前 intake 视频理解会做大小约束与降级策略，避免主流程直接卡死。

## 10) Fast Mental Model for AI Agents
1. 把 `runs` 看成可审阅状态机，不是一次性黑盒任务。
2. 把 `agent-configs` 看成“模型路由控制面”，不是运行时 prompt 文案。
3. 把 `asset_media_summary` 看成多阶段共享的多模态事实层。
4. 把 `feedback -> gm_memory` 看成跨 run 策略复用层（产品级 + 行业级）。
5. 遇到模型能力不确定，先 `POST /runs/preflight` 再创建 run。

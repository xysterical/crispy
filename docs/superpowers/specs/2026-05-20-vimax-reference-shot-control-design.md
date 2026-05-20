# ViMax 参考桥接与分镜控制 — 设计规格

> 整合 `upgrade-plan-vimax-reference-bridge.md`（Plan 1）和 `2026-05-19-vimax-inspired-video-control.md`（Plan 2），参考 ViMax 源码实现，采取务实精简路线。

## 目标

1. 同一 product 多张生成图之间保持产品外观、颜色、材质、比例一致
2. 分镜图不仅给人看，实际传入视频生成 API 作为视觉锚点
3. 结构化分镜合约让下游阶段有精确的镜头起止帧和运动描述
4. 增强 QA 对镜头计划遵守度的检查能力

## 非目标

- 不引入 LLM 驱动的参考图选择器（推迟 v1.1）
- 不多候选分镜生成+择优（推迟 v1.1）
- 不引入 Camera Tree 多机位建模
- 不改变数据库 schema
- 不新增 dashboard 控件
- 不新增 pipeline stage

## 架构原则

- **纯增量改动** — 所有改动用新增字段和可选参数，现有消费者不受影响
- **复用已有 LLM 调用点** — 不因 shot plan 增加额外 LLM API 成本
- **Provider 降级安全** — 参考图被忽略时输出不变，不报错
- **上限控制** — 参考图总数上限 4 张

---

## Phase 1: 数据管道打通（Reference Image Bridge）

### 1.1 新增历史最佳图获取方法

**文件:** `app/agents/runtime.py`

```python
def _best_historical_reference_images(self, product_code: str, limit: int = 2) -> list[dict]:
```

- 查询 `VariantAsset` 中 `asset_type="image"` 且关联 variant 的 `variant_score` 最高的记录
- 图片转为 base64 data URL
- 文件缺失时跳过，不报错
- 返回 `[{"uri": str, "description": str, "variant_score": float}]`

位置：在 `_reference_image_inputs()` (line 265) 附近。

### 1.2 扩展参考图输入

**文件:** `app/agents/runtime.py` — `_reference_image_inputs()` (line 265-279)

- 现有逻辑：从 `intake.image_references` 取最多 2 张
- 新增：追加 `_best_historical_reference_images()` 结果
- 总数上限 4 张

### 1.3 注入到图片生成阶段

**`run_copy_image_generation()` (line 972):**
- 构建 `reference_image_urls` 时合并历史最佳图
- 每张历史图附带描述文本 `"Previously generated winning product image"`

**`run_storyboard_image_generation()` (line 1406):**
- `_generate_image()` 调用时传入历史最佳产品图作为参考
- 保证分镜帧与产品图之间的一致性

### 1.4 分镜图传入视频生成

**`_build_task_input()` (`app/services/runs.py` line 667):**
```python
elif task.stage_name == "video_generation":
    payload = {
        **base,
        "video_scripts": _stage_output_optional(db, run.id, "video_scripting"),
        "storyboard_frames": _stage_output_optional(db, run.id, "storyboard_image_generation"),
    }
```

**`run_video_generation()` (`runtime.py` line 1542):**
- 从 `storyboard_frames` 提取 frame URI
- 按 variant_id 匹配对应 frame
- 传入 `_generate_video()` 的 `image_urls` 参数

**`_generate_video()` / `_generate_video_submit_only()` (line 168/197):**
- 新增可选参数 `reference_frame_urls: list[str] | None`
- 填入 `VideoGenRequest(image_urls=...)`

### 1.5 GmMemory 视觉引用（可选）

**文件:** `app/services/feedback.py`

写入 GmMemory 时，`content` 字典追加：
```json
{
  "reference_image_uri": "/assets/xxx/product_V1_image.png",
  "reference_image_prompt": "..."
}
```
不改变数据库 schema，利用 JSON 列灵活性。

---

## Phase 2: 结构化分镜合约（Structured Shot Contracts）

参考 ViMax 的 `ShotDescription`（首帧 ff_desc + 尾帧 lf_desc + 运动 motion_desc 三段式），简化适配电商场景。

### 2.1 新增 Pydantic 模型

**文件:** `app/schemas/contracts.py`

```python
class ShotFramePlan(BaseModel):
    """ViMax-style: 静态帧快照"""
    description: str
    visible_product_elements: list[str] = Field(default_factory=list)


class ShotPlanItem(BaseModel):
    """ViMax-style: 首帧/尾帧/运动三段式镜头合约"""
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

电商简化：
- 去掉 ViMax 的 `cam_idx`、`variation_type`、`ff_vis_char_idxs`（电商视频无角色/多机位）
- 去掉 `camera_role`、`reference_asset_requirements`（推迟 v1.1）

### 2.2 扩展 VideoScriptItem

```python
class VideoScriptItem(BaseModel):
    # 现有字段保持不变
    shot_list: list[str]  # 保留，向后兼容
    shot_plan: list[ShotPlanItem] = Field(default_factory=list)  # 新增
```

### 2.3 生成 shot plan

**文件:** `app/agents/runtime.py` — `run_video_scripting()` (line 1262)

**主要路径 — LLM structured output:**
- 复用已有的 `run_video_scripting()` LLM 调用
- 通过 tool use / structured output 生成 `shot_plan`
- 对每个 variant 推导 3-4 个结构化镜头
- **TikTok 模式 intent:** thumb_stop → product_proof → usage_demo → cta_packshot
- **通用模式 intent:** opening_problem → product_demo → benefit_proof → brand_cta

**回退路径 — 模板推导:**
- LLM 失败时，从 `shot_list` 字符串列表构造最小 shot plan
- 每个 shot_list 条目映射为一个 `ShotPlanItem`，首帧描述填入条目文本，尾帧留空

---

## Phase 3: 增强 QA 与评估上下文

### 3.1 QA prompt 增强

**文件:** `app/agents/runtime.py` — `run_visual_quality_assessment()` (line 1716)

在现有 QA prompt 中追加检查项（文本注入，不新增 LLM 调用）：
- 产品是否在首帧中清晰可见
- 生成画面是否匹配 shot plan 各镜头的 intent
- product_continuity_constraints 是否被遵守
- 分镜帧之间视觉连贯性

### 3.2 评估上下文增强

**文件:** `app/agents/runtime.py` — `_build_evaluation_context()` (line 1998)

追加字段：
```python
"shot_plan_summary": [...]
"storyboard_selected_frames": [...]
"visual_qa_shot_plan_issues": [...]
```

### 3.3 硬门禁不变

不放松现有 gate：文件缺失 → 重新生成，QA 不通过 → 重新生成，异步 pending → 人工审核。

---

## 涉及文件总览

| 文件 | Phase | 改动类型 | 预估行数 |
|---|---|---|---|
| `app/agents/runtime.py` | 1, 2, 3 | 新增方法 + 修改现有方法 | +130 |
| `app/schemas/contracts.py` | 2 | 新增 Pydantic 模型 | +30 |
| `app/services/runs.py` | 1 | 修改 `_build_task_input` | +5 |
| `app/services/feedback.py` | 1 | GmMemory content 追加 | +5 |
| `app/providers/llm.py` | - | 无需改动（已有字段） | 0 |
| **合计** | | | **~170** |

## 风险与降级

| 风险 | 降级策略 |
|---|---|
| Provider 忽略参考图 | 输出不变，no-op 降级 |
| 历史最佳图文件缺失 | 检查存在性，缺失跳过 |
| 参考图过多导致 API 拒绝 | 总数上限 4 张 |
| LLM shot plan 生成失败 | 回退到模板推导 |
| Provider 不支持 image_with_roles | 不传该字段 |

## 验证方法

1. 同一 product 连续跑两次 `copy_image_only`，检查第二次日志中 `reference_image_urls` 包含第一次获胜图 URI
2. 跑 `video_only` pipeline，检查 `VideoGenRequest.image_urls` 被填充
3. 检查 `video_scripting` 输出同时包含 `shot_list` 和 `shot_plan`
4. QA 日志中确认 shot-plan 遵守度检查被执行
5. 回归：`copy_image_only`、`dtc_site_image`、`marketplace_main_image` 模式行为不变

from __future__ import annotations

from typing import Literal

from sqlalchemy.orm import Session

from app.agents.registry import stage_agent
from app.orchestrator.state_machine import stage_plan_for
from app.services.marketplace_qa import is_marketplace_main_image
from app.services.agent_api_configs import resolve_agent_config
from app.services.creative_specs import TIKTOK_SHOP_VIDEO_DEFAULT_STYLE, TIKTOK_SHOP_VIDEO_STYLES

Severity = Literal["ok", "warn", "error"]


def _norm(value: str | None) -> str:
    return (value or "").strip().lower()


def _contains_any(value: str, hints: tuple[str, ...]) -> bool:
    return any(hint in value for hint in hints)


def _assess_image_understanding(provider: str | None, model: str | None) -> bool | None:
    p = _norm(provider)
    m = _norm(model)
    if not m and not p:
        return None
    if "deepseek" in m and not _contains_any(m, ("vl", "vision", "janus")):
        return False
    if _contains_any(
        m,
        (
            "kimi-k2.6",
            "kimi-k2.5",
            "gpt-4o",
            "gpt-4.1",
            "gpt-5",
            "gemini",
            "claude",
            "vision",
            "vl",
            "janus",
        ),
    ):
        return True
    if p in {"kimi", "openai", "xai"}:
        return None
    return None


def _assess_video_understanding(provider: str | None, model: str | None) -> bool | None:
    p = _norm(provider)
    m = _norm(model)
    if not m and not p:
        return None
    if "deepseek" in m and not _contains_any(m, ("vl", "vision", "janus")):
        return False
    if _contains_any(
        m,
        (
            "kimi-k2.6",
            "kimi-k2.5",
            "gemini",
            "qwen-vl",
            "video-understand",
        ),
    ):
        return True
    if p in {"kimi"}:
        return True
    if p in {"openai", "xai"}:
        return None
    return None


def _assess_image_generation(provider: str | None, model: str | None, api_base_url: str | None) -> bool | None:
    p = _norm(provider)
    m = _norm(model)
    b = _norm(api_base_url)
    if "/images/" in b:
        return True
    if _contains_any(
        m,
        (
            "gpt-image",
            "flux",
            "sdxl",
            "stable-diffusion",
            "recraft",
            "imagen",
            "dall",
        ),
    ):
        return True
    if _contains_any(m, ("deepseek", "kimi-k2", "gpt-4.1", "gpt-5", "claude")):
        return False
    if p in {"openai", "apimart"}:
        return None
    return None


def _assess_reference_image_edit(
    provider: str | None,
    model: str | None,
    api_base_url: str | None,
    extra: dict | None,
) -> bool | None:
    image_extra = ((extra or {}).get("image_config") or {}) if isinstance(extra, dict) else {}
    for key in ("supports_reference_edit", "reference_edit_supported", "supports_image_references"):
        if key in image_extra:
            return bool(image_extra.get(key))
    p = _norm(provider)
    m = _norm(model)
    b = _norm(api_base_url)
    if "/images/" in b and _contains_any(m, ("gpt-image", "flux-kontext", "qwen-image-edit", "seedream", "recraft")):
        return True
    if _contains_any(m, ("gpt-image", "flux-kontext", "qwen-image-edit", "image-edit", "seedream", "recraft")):
        return True
    if _contains_any(m, ("dall", "sdxl", "stable-diffusion")):
        return None
    if p in {"openai", "apimart", "xai", "kimi"}:
        return None
    return None


def _assess_video_generation(provider: str | None, model: str | None, api_base_url: str | None) -> bool | None:
    p = _norm(provider)
    m = _norm(model)
    b = _norm(api_base_url)
    if "/videos/" in b:
        return True
    if _contains_any(
        m,
        (
            "seedance",
            "doubao-seedance",
            "sora",
            "veo",
            "kling",
            "hunyuan-video",
            "runway",
            "pika",
            "vidu",
        ),
    ):
        return True
    if _contains_any(m, ("deepseek", "kimi-k2", "gpt-4.1", "gpt-5", "claude", "gemini")):
        return False
    if p in {"openai", "apimart"}:
        return None
    return None


def _merge_severity(a: Severity, b: Severity) -> Severity:
    order = {"ok": 0, "warn": 1, "error": 2}
    return a if order[a] >= order[b] else b


def preflight_run_capabilities(
    db: Session,
    *,
    pipeline_mode: str,
    has_image_inputs: bool,
    has_video_inputs: bool,
    creative_specs: dict | None = None,
) -> dict:
    stage_plan = stage_plan_for(pipeline_mode)
    creative_specs = creative_specs or {}
    marketplace_goal = pipeline_mode == "marketplace_main_image" or is_marketplace_main_image(creative_specs)
    checks: list[dict] = []
    overall: Severity = "ok"

    def add_check(
        *,
        key: str,
        severity: Severity,
        message: str,
        stage_name: str | None = None,
        agent_name: str | None = None,
    ) -> None:
        nonlocal overall
        overall = _merge_severity(overall, severity)
        checks.append(
            {
                "key": key,
                "severity": severity,
                "message": message,
                "stage_name": stage_name,
                "agent_name": agent_name,
            }
        )

    def resolved(stage_name: str) -> tuple[str, dict]:
        agent_name = stage_agent(stage_name)
        cfg = resolve_agent_config(db, agent_name=agent_name, run_provider="openai", run_model="gpt-4.1")
        return agent_name, cfg

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

    if "intake" in stage_plan and (has_image_inputs or has_video_inputs):
        agent_name, cfg = resolved("intake")
        if not cfg.get("api_key_available"):
            add_check(
                key="intake.api_key",
                severity="warn",
                message=(
                    f"Intake agent `{agent_name}` has no loaded API key "
                    f"({cfg.get('api_key_env') or 'unset'}). Real multimodal understanding may fallback or fail."
                ),
                stage_name="intake",
                agent_name=agent_name,
            )
        if has_image_inputs:
            support = _assess_image_understanding(cfg.get("provider_name"), cfg.get("model_name"))
            if support is False:
                add_check(
                    key="intake.image_understanding",
                    severity="error",
                    message=(
                        f"Model `{cfg.get('model_name')}` on `{cfg.get('provider_name')}` is incompatible with image understanding in chat."
                    ),
                    stage_name="intake",
                    agent_name=agent_name,
                )
            elif support is None:
                add_check(
                    key="intake.image_understanding",
                    severity="warn",
                    message=(
                        f"Image understanding support is unknown for `{cfg.get('provider_name')}/{cfg.get('model_name')}`. "
                        "If unsupported, intake may degrade to weak summaries."
                    ),
                    stage_name="intake",
                    agent_name=agent_name,
                )
        if has_video_inputs:
            support = _assess_video_understanding(cfg.get("provider_name"), cfg.get("model_name"))
            if support is False:
                add_check(
                    key="intake.video_understanding",
                    severity="error",
                    message=(
                        f"Model `{cfg.get('model_name')}` on `{cfg.get('provider_name')}` is incompatible with video understanding in chat."
                    ),
                    stage_name="intake",
                    agent_name=agent_name,
                )
            elif support is None:
                add_check(
                    key="intake.video_understanding",
                    severity="warn",
                    message=(
                        f"Video understanding support is unknown for `{cfg.get('provider_name')}/{cfg.get('model_name')}`. "
                        "Recommended known-good: kimi-k2.6 / kimi-k2.5."
                    ),
                    stage_name="intake",
                    agent_name=agent_name,
                )

    if "copy_image_generation" in stage_plan:
        agent_name, cfg = resolved("copy_image_generation")
        if marketplace_goal and not (has_image_inputs or has_video_inputs):
            add_check(
                key="marketplace_main_image.reference_media",
                severity="error",
                message="Marketplace main-image generation requires at least one uploaded product image or video reference.",
                stage_name="intake",
                agent_name="gm_orchestrator",
            )
        if not cfg.get("image_api_key_available"):
            add_check(
                key="copy_image_generation.image_api_key",
                severity="warn",
                message=(
                    f"Generation image API key is not loaded ({cfg.get('image_api_key_env') or 'unset'}). "
                    "Image generation may fallback or fail."
                ),
                stage_name="copy_image_generation",
                agent_name=agent_name,
            )
        support = _assess_image_generation(
            cfg.get("image_provider_name"),
            cfg.get("image_model_name"),
            cfg.get("image_api_base_url"),
        )
        if support is False:
            add_check(
                key="copy_image_generation.image_generation",
                severity="error",
                message=(
                    f"Image model config looks incompatible: `{cfg.get('image_provider_name')}/{cfg.get('image_model_name')}` "
                    f"with base_url `{cfg.get('image_api_base_url') or 'unset'}`."
                ),
                stage_name="copy_image_generation",
                agent_name=agent_name,
            )
        elif support is None:
            add_check(
                key="copy_image_generation.image_generation",
                severity="warn",
                message=(
                    f"Image generation compatibility is unknown for `{cfg.get('image_provider_name')}/{cfg.get('image_model_name')}`."
                ),
                stage_name="copy_image_generation",
                agent_name=agent_name,
            )
        if marketplace_goal:
            reference_support = _assess_reference_image_edit(
                cfg.get("image_provider_name"),
                cfg.get("image_model_name"),
                cfg.get("image_api_base_url"),
                cfg.get("extra"),
            )
            if reference_support is False:
                add_check(
                    key="copy_image_generation.reference_edit",
                    severity="error",
                    message=(
                        "Marketplace main-image generation requires reference/edit image support, but image_config explicitly disables it."
                    ),
                    stage_name="copy_image_generation",
                    agent_name=agent_name,
                )
            elif reference_support is None:
                add_check(
                    key="copy_image_generation.reference_edit",
                    severity="warn",
                    message=(
                        f"Reference/edit support is unknown for `{cfg.get('image_provider_name')}/{cfg.get('image_model_name')}`. "
                        "Generated images will be held for marketplace QA and human review if fidelity cannot be trusted."
                    ),
                    stage_name="copy_image_generation",
                    agent_name=agent_name,
                )

    if "video_generation" in stage_plan:
        agent_name, cfg = resolved("video_generation")
        if not cfg.get("video_api_key_available"):
            add_check(
                key="video_generation.video_api_key",
                severity="warn",
                message=(
                    f"Generation video API key is not loaded ({cfg.get('video_api_key_env') or 'unset'}). "
                    "Video generation may fallback or fail."
                ),
                stage_name="video_generation",
                agent_name=agent_name,
            )
        support = _assess_video_generation(
            cfg.get("video_provider_name"),
            cfg.get("video_model_name"),
            cfg.get("video_api_base_url"),
        )
        if support is False:
            add_check(
                key="video_generation.video_generation",
                severity="error",
                message=(
                    f"Video model config looks incompatible: `{cfg.get('video_provider_name')}/{cfg.get('video_model_name')}` "
                    f"with base_url `{cfg.get('video_api_base_url') or 'unset'}`."
                ),
                stage_name="video_generation",
                agent_name=agent_name,
            )
        elif support is None:
            add_check(
                key="video_generation.video_generation",
                severity="warn",
                message=(
                    f"Video generation compatibility is unknown for `{cfg.get('video_provider_name')}/{cfg.get('video_model_name')}`."
                ),
                stage_name="video_generation",
                agent_name=agent_name,
            )

    if not checks:
        checks.append(
            {
                "key": "preflight.ok",
                "severity": "ok",
                "message": "No obvious compatibility risks detected for current mode and inputs.",
                "stage_name": None,
                "agent_name": None,
            }
        )

    errors = sum(1 for item in checks if item["severity"] == "error")
    warns = sum(1 for item in checks if item["severity"] == "warn")
    summary = f"Preflight completed: {errors} error(s), {warns} warning(s)."
    return {
        "ok": overall != "error",
        "severity": overall,
        "summary": summary,
        "checks": checks,
    }

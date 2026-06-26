from __future__ import annotations

from typing import Literal

from sqlalchemy.orm import Session

from app.agents.registry import stage_agent
from app.orchestrator.state_machine import stage_plan_for
from app.services.marketplace_qa import is_marketplace_main_image
from app.services.agent_api_configs import resolve_agent_config
from app.services.creative_specs import (
    TIKTOK_SHOP_VIDEO_DEFAULT_STYLE,
    TIKTOK_SHOP_VIDEO_STYLES,
    get_social_review_contract,
    normalize_storyboard_candidate_count,
)
from app.services.capability_registry import capability_spec

Severity = Literal["ok", "warn", "error"]


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
    capabilities: list[dict] = []
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

    def add_capability(key: str, capability: str, stage_name: str, agent_name: str, cfg: dict) -> bool | None:
        spec = capability_spec(
            key=key,
            capability=capability,
            stage_name=stage_name,
            agent_name=agent_name,
            cfg=cfg,
        )
        capabilities.append(spec.as_dict())
        return spec.supported

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
            support = add_capability("intake.image_understanding", "image_understanding", "intake", agent_name, cfg)
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
            support = add_capability("intake.video_understanding", "video_understanding", "intake", agent_name, cfg)
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
        support = add_capability("copy_image_generation.image_generation", "image_generation", "copy_image_generation", agent_name, cfg)
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
            reference_support = add_capability("copy_image_generation.reference_edit", "reference_image_edit", "copy_image_generation", agent_name, cfg)
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

    if "storyboard_image_generation" in stage_plan:
        agent_name, cfg = resolved("storyboard_image_generation")
        if not cfg.get("image_api_key_available"):
            add_check(
                key="storyboard_image_generation.image_api_key",
                severity="warn",
                message=(
                    f"Storyboard image API key is not loaded ({cfg.get('image_api_key_env') or 'unset'}). "
                    "Storyboard generation may fallback or fail."
                ),
                stage_name="storyboard_image_generation",
                agent_name=agent_name,
            )
        support = add_capability("storyboard_image_generation.image_generation", "image_generation", "storyboard_image_generation", agent_name, cfg)
        if support is False:
            add_check(
                key="storyboard_image_generation.image_generation",
                severity="error",
                message=(
                    f"Storyboard image model config looks incompatible: `{cfg.get('image_provider_name')}/{cfg.get('image_model_name')}` "
                    f"with base_url `{cfg.get('image_api_base_url') or 'unset'}`."
                ),
                stage_name="storyboard_image_generation",
                agent_name=agent_name,
            )
        elif support is None:
            add_check(
                key="storyboard_image_generation.image_generation",
                severity="warn",
                message=(
                    f"Storyboard image generation compatibility is unknown for `{cfg.get('image_provider_name')}/{cfg.get('image_model_name')}`."
                ),
                stage_name="storyboard_image_generation",
                agent_name=agent_name,
            )
        try:
            candidate_count = normalize_storyboard_candidate_count(
                creative_specs.get("storyboard_candidate_count")
            )
        except ValueError:
            candidate_count = 1
        if candidate_count > 1:
            add_check(
                key="storyboard_image_generation.multi_candidate_cost",
                severity="warn",
                message=(
                    f"Storyboard multi-candidate generation is set to {candidate_count} candidates per beat. "
                    "Expect higher image cost and a slower review surface."
                ),
                stage_name="storyboard_image_generation",
                agent_name=agent_name,
            )
            if support is not True:
                add_check(
                    key="storyboard_image_generation.candidate_selection",
                    severity="warn",
                    message=(
                        "Storyboard multi-candidate selection is enabled, but image generation support is not known-good. "
                        "Expect weaker automatic candidate ranking and rely on operator review."
                    ),
                    stage_name="storyboard_image_generation",
                    agent_name=agent_name,
                )

    if "visual_quality_assessment" in stage_plan and "video_generation" in stage_plan:
        review_agent_name, _ = resolved("visual_quality_assessment")
        social_review_contract = get_social_review_contract(
            creative_specs.get("platform") or "",
            pipeline_mode,
            creative_specs,
        )
        required_checks = {
            str(check).strip().lower()
            for check in (social_review_contract.get("required_checks") or [])
            if str(check).strip()
        }
        if not required_checks or {"first_frame_clarity", "continuity"} & required_checks:
            add_check(
                key="visual_quality_assessment.frame_review",
                severity="warn",
                message=(
                    "Video outputs may still need frame review in visual QA for first-frame clarity, continuity, or remote provider gaps."
                ),
                stage_name="visual_quality_assessment",
                agent_name=review_agent_name,
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
        support = add_capability("video_generation.video_generation", "video_generation", "video_generation", agent_name, cfg)
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
        "capabilities": capabilities,
    }

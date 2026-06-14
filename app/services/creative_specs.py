from __future__ import annotations

from copy import deepcopy
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.data.models import CreativePreset

TIKTOK_SHOP_VIDEO_STYLES = {"ugc_demo", "direct_response_ad", "shop_account_content"}
TIKTOK_SHOP_VIDEO_DEFAULT_STYLE = "ugc_demo"
TIKTOK_SHOP_VIDEO_PRESET = "tiktok_shop_conversion_12s"
DTC_SITE_IMAGE_PRESET = "dtc_site_image_pack"

DTC_SITE_SURFACE_LIBRARY: dict[str, dict] = {
    "homepage_hero": {
        "site_surface": "homepage_hero",
        "display_name": "Homepage Hero",
        "composition_focus": "brand_story_scene",
        "framing_guidance": "Use a premium lifestyle scene with the product integrated naturally and the subject anchored away from center when possible.",
        "negative_space_policy": "headline-safe negative space",
        "product_visibility_rule": "The product must remain clearly recognizable without filling the entire frame.",
        "backdrop_style": "editorial, immersive, premium environment",
        "forbidden_elements": [
            "dense retail collage",
            "tiny illegible product",
            "tight crop with no room for homepage headline treatment",
        ],
        "review_hints": [
            "Check that there is headline-safe space for a homepage message or CTA.",
            "Check that the frame feels like brand atmosphere, not a cramped product tile.",
            "Check that the product is still clearly recognizable within the wider story scene.",
        ],
    },
    "pdp_primary": {
        "site_surface": "pdp_primary",
        "display_name": "PDP Primary",
        "composition_focus": "product_dominant_detail",
        "framing_guidance": "Keep the product front-loaded, cleanly framed, and easy to inspect at a glance.",
        "negative_space_policy": "avoid oversized hero-banner empty space",
        "product_visibility_rule": "Product should dominate the frame with clearly inspectable details.",
        "backdrop_style": "clean, ecommerce-first, low distraction backdrop",
        "forbidden_elements": [
            "busy lifestyle scene",
            "small product in oversized environment",
            "heavy atmospheric storytelling that hides details",
        ],
        "review_hints": [
            "Check that the product occupies enough of the frame for a PDP first image.",
            "Check that material or structure details are easy to inspect at a glance.",
            "Check that the background stays clean and does not compete with the product.",
        ],
    },
}

SOCIAL_REVIEW_CONTRACTS: dict[tuple[str, str], dict] = {
    ("tiktok", "tiktok_shop_video"): {
        "review_profile": "social_video",
        "preferred_video_size": "9:16",
        "required_checks": [
            "first_frame_clarity",
            "product_truth",
            "continuity",
            "cta_clarity",
        ],
        "evaluation_dimensions": [
            "thumb_stop_power",
            "product_clarity",
            "purchase_intent",
            "watch_through_potential",
        ],
    },
    ("meta", "copy_image_only"): {
        "review_profile": "social_image",
        "preferred_image_size": "1:1",
        "required_checks": [
            "product_visibility",
            "text_overlay_risk",
            "claim_safety",
        ],
        "evaluation_dimensions": [
            "hook_appeal",
            "visual_execution",
            "brand_alignment",
        ],
    },
}

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
    DTC_SITE_IMAGE_PRESET: {
        "image_size": "4:5",
        "video_size": "4:5",
        "resolution": "1600px",
        "video_duration_seconds": 5,
        "asset_goal": "dtc_site_image",
        "site_surface": "pdp_primary",
        "platform_targets": ["shopify"],
    },
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


def get_dtc_site_surface_strategy(creative_specs: dict | None) -> dict:
    specs = creative_specs or {}
    if str(specs.get("asset_goal") or "").strip() != "dtc_site_image":
        return {}
    surface = str(specs.get("site_surface") or "pdp_primary").strip().lower()
    return deepcopy(DTC_SITE_SURFACE_LIBRARY.get(surface) or DTC_SITE_SURFACE_LIBRARY["pdp_primary"])


def get_dtc_site_review_hints(creative_specs: dict | None) -> list[str]:
    strategy = get_dtc_site_surface_strategy(creative_specs)
    return list(strategy.get("review_hints") or [])


def get_social_review_contract(channel: str | None, pipeline_mode: str | None, creative_specs: dict | None = None) -> dict:
    specs = creative_specs or {}
    key = (str(channel or "").strip().lower(), str(pipeline_mode or "").strip().lower())
    base = deepcopy(SOCIAL_REVIEW_CONTRACTS.get(key) or {})
    if not base:
        return {
            "review_profile": "generic",
            "preferred_image_size": specs.get("image_size"),
            "preferred_video_size": specs.get("video_size"),
            "required_checks": [],
            "evaluation_dimensions": [],
        }
    if "preferred_image_size" not in base and specs.get("image_size"):
        base["preferred_image_size"] = specs["image_size"]
    if "preferred_video_size" not in base and specs.get("video_size"):
        base["preferred_video_size"] = specs["video_size"]
    return base


def normalize_storyboard_candidate_count(value: object | None) -> int:
    if value in (None, ""):
        return 1
    try:
        candidate_count = int(value)
    except Exception as exc:
        raise ValueError("creative_specs.storyboard_candidate_count must be integer") from exc
    if candidate_count < 1 or candidate_count > 4:
        raise ValueError("creative_specs.storyboard_candidate_count must be within 1..4")
    return candidate_count


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
    resolved["storyboard_candidate_count"] = normalize_storyboard_candidate_count(
        resolved.get("storyboard_candidate_count")
    )

    if resolved.get("asset_goal") == "dtc_site_image" or "site_surface" in resolved:
        surface = str(resolved.get("site_surface") or "").strip().lower()
        if surface not in DTC_SITE_SURFACE_LIBRARY:
            supported = ", ".join(sorted(DTC_SITE_SURFACE_LIBRARY.keys()))
            raise ValueError(f"creative_specs.site_surface must be one of: {supported}")
    return resolved


def resolve_creative_specs_from_user_preset(db: Session, preset_id: str) -> dict:
    preset = get_creative_preset(db, preset_id)
    return {
        "image_size": preset.image_size or "1:1",
        "video_size": preset.video_size or "1:1",
        "resolution": preset.resolution or "720p",
        "video_duration_seconds": preset.video_duration_seconds or 5,
        "storyboard_candidate_count": 1,
        "platform_targets": preset.platform_targets or {},
    }

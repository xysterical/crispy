from __future__ import annotations

from copy import deepcopy
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.data.models import CreativePreset

TIKTOK_SHOP_VIDEO_STYLES = {"ugc_demo", "direct_response_ad", "shop_account_content"}
TIKTOK_SHOP_VIDEO_DEFAULT_STYLE = "ugc_demo"
TIKTOK_SHOP_VIDEO_PRESET = "tiktok_shop_conversion_12s"

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
    return resolved


def resolve_creative_specs_from_user_preset(db: Session, preset_id: str) -> dict:
    preset = get_creative_preset(db, preset_id)
    return {
        "image_size": preset.image_size or "1:1",
        "video_size": preset.video_size or "1:1",
        "resolution": preset.resolution or "720p",
        "video_duration_seconds": preset.video_duration_seconds or 5,
        "platform_targets": preset.platform_targets or {},
    }

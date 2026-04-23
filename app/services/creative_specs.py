from __future__ import annotations

from copy import deepcopy


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
}


def list_creative_presets() -> dict[str, dict]:
    return deepcopy(CREATIVE_PRESETS)


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

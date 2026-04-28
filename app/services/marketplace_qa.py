from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any


MARKETPLACE_ASSET_GOAL = "marketplace_main_image"
DEFAULT_MARKETPLACE_PLATFORMS = ["tiktok_shop", "shopify", "alibaba", "amazon"]
MARKETPLACE_REVIEW_TAGS = {
    "color_mismatch",
    "edge_halo",
    "too_flat",
    "shadow_too_strong",
    "wrong_logo",
    "product_fill_low",
}


def is_marketplace_main_image(creative_specs: dict | None) -> bool:
    return str((creative_specs or {}).get("asset_goal") or "").strip() == MARKETPLACE_ASSET_GOAL


def normalize_platform_targets(creative_specs: dict | None) -> list[str]:
    raw = (creative_specs or {}).get("platform_targets")
    if isinstance(raw, list):
        targets = [str(item).strip().lower() for item in raw if str(item).strip()]
    elif isinstance(raw, str) and raw.strip():
        targets = [item.strip().lower() for item in raw.split(",") if item.strip()]
    else:
        targets = list(DEFAULT_MARKETPLACE_PLATFORMS)
    return targets or list(DEFAULT_MARKETPLACE_PLATFORMS)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def infer_visual_identity(
    *,
    product_name: str,
    category_tags: list[str],
    media_summary: str,
    image_references: list[dict],
    video_references: list[dict],
) -> dict:
    text = media_summary.lower()
    color_words = [
        "black",
        "white",
        "red",
        "blue",
        "green",
        "yellow",
        "orange",
        "pink",
        "purple",
        "gray",
        "grey",
        "silver",
        "gold",
        "brown",
        "beige",
        "transparent",
    ]
    material_words = [
        "metal",
        "steel",
        "aluminum",
        "plastic",
        "silicone",
        "rubber",
        "leather",
        "nylon",
        "cotton",
        "glass",
        "ceramic",
        "wood",
        "fabric",
    ]
    colors = [word for word in color_words if word in text]
    materials = [word for word in material_words if word in text]
    best_frames: list[str] = []
    for row in video_references:
        for frame_uri in row.get("frame_placeholders") or row.get("frame_uris") or []:
            if isinstance(frame_uri, str) and frame_uri:
                best_frames.append(frame_uri)
            if len(best_frames) >= 4:
                break
        if len(best_frames) >= 4:
            break
    best_images = [
        str(row.get("uri"))
        for row in image_references
        if isinstance(row, dict) and isinstance(row.get("uri"), str) and row.get("uri")
    ][:4]
    warnings: list[str] = []
    if not best_images and not best_frames:
        warnings.append("no_reference_media")
    if not media_summary.strip():
        warnings.append("media_summary_empty")
    if not colors:
        warnings.append("primary_color_uncertain")
    if not materials:
        warnings.append("material_uncertain")
    return {
        "product_type": product_name,
        "category_tags": category_tags,
        "colors": colors,
        "materials": materials,
        "visible_text_logo": [],
        "must_preserve_details": [
            product_name,
            *[f"color:{item}" for item in colors[:3]],
            *[f"material:{item}" for item in materials[:3]],
        ],
        "missing_fact_warnings": warnings,
        "best_reference_images": best_images,
        "best_reference_frames": best_frames,
        "source_media_count": {
            "images": len(image_references),
            "videos": len(video_references),
            "sampled_video_frames": len(best_frames),
        },
        "raw_media_summary": media_summary[:2400],
    }


def _safe_local_path(uri: str | None) -> Path | None:
    if not uri or uri.startswith(("http://", "https://", "data:")):
        return None
    return Path(uri)


def _white_pixel(pixel: tuple[int, int, int], threshold: int = 246) -> bool:
    return pixel[0] >= threshold and pixel[1] >= threshold and pixel[2] >= threshold


def _border_pixels(image) -> list[tuple[int, int, int]]:
    width, height = image.size
    pixels = image.load()
    rows: list[tuple[int, int, int]] = []
    for x in range(width):
        rows.append(pixels[x, 0])
        rows.append(pixels[x, height - 1])
    for y in range(height):
        rows.append(pixels[0, y])
        rows.append(pixels[width - 1, y])
    return rows


def _image_marketplace_metrics(path: Path, export_size_px: int) -> dict[str, Any]:
    try:
        from PIL import Image, ImageFilter, ImageStat  # type: ignore
    except Exception as exc:
        return {"decode_error": f"pillow_unavailable: {exc}"}
    try:
        with Image.open(path) as original:
            width, height = original.size
            image = original.convert("RGB")
            sample = image.resize((min(256, width), min(256, height)))
            sample_width, sample_height = sample.size
            pixels = sample.load()
            nonwhite: list[tuple[int, int]] = []
            for y in range(sample_height):
                for x in range(sample_width):
                    if not _white_pixel(pixels[x, y]):
                        nonwhite.append((x, y))
            border = _border_pixels(sample)
            border_white_ratio = (
                sum(1 for pixel in border if _white_pixel(pixel)) / len(border)
                if border
                else 0.0
            )
            if nonwhite:
                xs = [item[0] for item in nonwhite]
                ys = [item[1] for item in nonwhite]
                bbox = (min(xs), min(ys), max(xs), max(ys))
                bbox_width = bbox[2] - bbox[0] + 1
                bbox_height = bbox[3] - bbox[1] + 1
                fill_max_side = max(bbox_width / sample_width, bbox_height / sample_height)
                fill_area = (bbox_width * bbox_height) / (sample_width * sample_height)
            else:
                bbox = None
                fill_max_side = 0.0
                fill_area = 0.0
            edge_image = sample.filter(ImageFilter.FIND_EDGES).convert("L")
            edge_stat = ImageStat.Stat(edge_image)
            edge_score = float(edge_stat.mean[0])
            return {
                "width": width,
                "height": height,
                "aspect_ratio": round(width / height, 4) if height else None,
                "export_size_px": export_size_px,
                "border_white_ratio": round(border_white_ratio, 4),
                "product_bbox_sample": bbox,
                "product_fill_max_side": round(fill_max_side, 4),
                "product_fill_area": round(fill_area, 4),
                "edge_score": round(edge_score, 4),
            }
    except Exception as exc:
        return {"decode_error": str(exc)[:240]}


def _add_check(
    checks: list[dict],
    flags: list[str],
    *,
    key: str,
    status: str,
    message: str,
    flag: str | None = None,
) -> None:
    checks.append({"key": key, "status": status, "message": message})
    if flag:
        flags.append(flag)


def inspect_marketplace_image(
    *,
    uri: str | None,
    payload: dict | None,
    creative_specs: dict | None,
    visual_identity: dict | None = None,
) -> dict[str, Any]:
    payload = payload or {}
    creative_specs = creative_specs or {}
    visual_identity = visual_identity or {}
    export_size_px = int(creative_specs.get("export_size_px") or 2000)
    platforms = normalize_platform_targets(creative_specs)
    checks: list[dict[str, Any]] = []
    flags: list[str] = []
    score = 100.0

    path = _safe_local_path(uri)
    if path is None:
        _add_check(checks, flags, key="uri", status="fail", message="Marketplace image must be a local generated file.", flag="marketplace_missing_local_file")
        return _marketplace_result("fail", 0.0, flags, checks, {}, platforms)
    if not path.exists() or not path.is_file():
        _add_check(checks, flags, key="file", status="fail", message="Marketplace image file is missing.", flag="marketplace_missing_file")
        return _marketplace_result("fail", 0.0, flags, checks, {}, platforms)
    if path.stat().st_size < 512:
        _add_check(checks, flags, key="file_size", status="fail", message="Marketplace image is empty or placeholder-sized.", flag="marketplace_placeholder")
        score -= 80

    metrics = _image_marketplace_metrics(path, export_size_px)
    if metrics.get("decode_error"):
        _add_check(checks, flags, key="image_decode", status="fail", message=str(metrics["decode_error"]), flag="marketplace_decode_error")
        return _marketplace_result("fail", 0.0, flags, checks, metrics, platforms)

    width = int(metrics.get("width") or 0)
    height = int(metrics.get("height") or 0)
    if min(width, height) < 1000:
        _add_check(checks, flags, key="resolution", status="fail", message="Marketplace master image should be at least 1000px on each side.", flag="marketplace_resolution_low")
        score -= 35
    elif min(width, height) < export_size_px:
        _add_check(checks, flags, key="export_resolution", status="warn", message=f"Image is below target export size {export_size_px}px.", flag="marketplace_export_size_under_target")
        score -= 8
    else:
        _add_check(checks, flags, key="resolution", status="pass", message="Image resolution meets marketplace master target.")

    aspect = float(metrics.get("aspect_ratio") or 0.0)
    if aspect and abs(aspect - 1.0) > 0.04:
        _add_check(checks, flags, key="aspect_ratio", status="fail", message="Marketplace main image must be square.", flag="marketplace_not_square")
        score -= 30

    border_white_ratio = float(metrics.get("border_white_ratio") or 0.0)
    if border_white_ratio < 0.86:
        _add_check(checks, flags, key="background", status="fail", message="Image border is not consistently pure white.", flag="marketplace_background_not_white")
        score -= 40
    elif border_white_ratio < 0.96:
        _add_check(checks, flags, key="background", status="warn", message="Background is close to white but may contain shadows or color cast.", flag="marketplace_background_not_pure_white")
        score -= 12
    else:
        _add_check(checks, flags, key="background", status="pass", message="Background border is pure white.")

    fill_max_side = float(metrics.get("product_fill_max_side") or 0.0)
    if fill_max_side < 0.45:
        _add_check(checks, flags, key="product_fill", status="fail", message="Product occupies too little of the frame.", flag="product_fill_low")
        score -= 30
    elif fill_max_side < 0.60:
        _add_check(checks, flags, key="product_fill", status="warn", message="Product fill is usable but smaller than a strong marketplace main image.", flag="product_fill_low")
        score -= 10
    elif fill_max_side > 0.98:
        _add_check(checks, flags, key="product_crop", status="warn", message="Product may be cropped too tightly.", flag="marketplace_crop_risk")
        score -= 8
    else:
        _add_check(checks, flags, key="product_fill", status="pass", message="Product fill is in a marketplace-ready range.")

    edge_score = float(metrics.get("edge_score") or 0.0)
    if edge_score < 1.0:
        _add_check(checks, flags, key="edge_detail", status="warn", message="Image has very weak edge detail; check blur or over-smoothing.", flag="marketplace_edge_detail_low")
        score -= 8

    source = str(payload.get("source") or "").lower()
    if source == "placeholder":
        _add_check(checks, flags, key="provider_source", status="fail", message="Provider returned a placeholder image.", flag="marketplace_placeholder")
        score -= 70
    if int(payload.get("reference_source_count") or 0) <= 0:
        _add_check(checks, flags, key="reference_fidelity", status="fail", message="Marketplace main image requires source media references.", flag="marketplace_missing_reference")
        score -= 35
    else:
        _add_check(checks, flags, key="reference_fidelity", status="pass", message="Reference media was attached for source-product fidelity.")

    prompt = str(payload.get("prompt") or "").lower()
    text_overlay_negated = any(term in prompt for term in ("no text overlay", "no text overlays", "do not invent"))
    if "text overlay" in prompt and not text_overlay_negated:
        _add_check(checks, flags, key="text_overlay", status="fail", message="Prompt appears to allow text overlay.", flag="marketplace_text_overlay_risk")
        score -= 25
    scene_terms = any(term in prompt for term in ("lifestyle", "outdoor", "person holding", "model wearing", "props", "scene background"))
    scene_negated = any(term in prompt for term in ("no props", "no model", "no scene background", "do not invent accessories", "do not invent"))
    if scene_terms and not scene_negated:
        _add_check(checks, flags, key="props_models", status="warn", message="Prompt may introduce props, people, or non-white scenes.", flag="marketplace_prop_or_model_risk")
        score -= 10
    if any(term in prompt for term in ("3d render", "cgi", "illustration", "cartoon")):
        _add_check(checks, flags, key="digital_rendering", status="warn", message="Marketplace product photo should not look like a digital render.", flag="marketplace_digital_rendering_risk")
        score -= 10

    if visual_identity.get("missing_fact_warnings"):
        _add_check(
            checks,
            flags,
            key="source_identity",
            status="info",
            message="Product visual identity has unresolved source facts.",
            flag="marketplace_identity_uncertain",
        )
        score -= 2

    fail_count = sum(1 for check in checks if check["status"] == "fail")
    warn_count = sum(1 for check in checks if check["status"] in {"warn", "manual_review"})
    status = "fail" if fail_count else "warn" if warn_count else "pass"
    return _marketplace_result(status, max(0.0, round(score, 2)), flags, checks, metrics, platforms)


def _marketplace_result(
    status: str,
    score: float,
    flags: list[str],
    checks: list[dict],
    metrics: dict,
    platforms: list[str],
) -> dict[str, Any]:
    readiness = {}
    for platform in platforms:
        readiness[platform] = status
    return {
        "status": status,
        "score": score,
        "flags": sorted(set(flags)),
        "checks": checks,
        "metrics": metrics,
        "platform_readiness": readiness,
        "export_ready": status == "pass",
        "inspected_at": _now_iso(),
    }

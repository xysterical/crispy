from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_ratio(raw: str | None) -> float | None:
    if not raw or ":" not in raw:
        return None
    left, right = raw.split(":", 1)
    try:
        width = float(left.strip())
        height = float(right.strip())
    except ValueError:
        return None
    if width <= 0 or height <= 0:
        return None
    return width / height


def _safe_path(uri: str | None) -> Path | None:
    if not uri or uri.startswith(("http://", "https://", "data:")):
        return None
    return Path(uri)


def _image_metrics(path: Path) -> dict[str, Any]:
    try:
        from PIL import Image, ImageStat  # type: ignore
    except Exception:
        return {}
    try:
        with Image.open(path) as image:
            width, height = image.size
            converted = image.convert("RGB").resize((64, 64))
            stat = ImageStat.Stat(converted)
            extrema = converted.getextrema()
            dynamic_range = max(channel[1] - channel[0] for channel in extrema)
            mean_luma = sum(stat.mean) / 3
            return {
                "width": width,
                "height": height,
                "aspect_ratio": round(width / height, 4) if height else None,
                "dynamic_range": round(dynamic_range, 2),
                "mean_luma": round(mean_luma, 2),
            }
    except Exception as exc:
        return {"decode_error": str(exc)[:240]}


def _has_mp4_signature(path: Path) -> bool:
    try:
        header = path.read_bytes()[:32]
    except Exception:
        return False
    return b"ftyp" in header or header.startswith(b"\x00\x00\x00")


def inspect_visual_asset(
    *,
    asset_type: str,
    uri: str | None,
    payload: dict | None = None,
    expected_ratio: str | None = None,
) -> dict[str, Any]:
    payload = payload or {}
    checks: list[dict[str, Any]] = []
    flags: list[str] = []
    score = 100.0
    path = _safe_path(uri)
    if uri and uri.startswith(("http://", "https://", "data:")):
        checks.append({"key": "remote_asset", "status": "warn", "message": "Remote/data URI cannot be locally inspected."})
        flags.append("visual_qa_remote_unchecked")
        score -= 10
        return {
            "status": "warn",
            "score": max(0.0, score),
            "flags": flags,
            "checks": checks,
            "inspected_at": _now_iso(),
        }
    if path is None:
        checks.append({"key": "uri", "status": "fail", "message": "Asset URI is missing."})
        return {"status": "fail", "score": 0.0, "flags": ["visual_qa_missing_uri"], "checks": checks, "inspected_at": _now_iso()}
    if not path.exists():
        checks.append({"key": "file", "status": "fail", "message": "Asset file does not exist."})
        return {"status": "fail", "score": 0.0, "flags": ["visual_qa_missing_file"], "checks": checks, "inspected_at": _now_iso()}
    size_bytes = path.stat().st_size
    status = str(payload.get("generation_status") or "").lower()
    source = str(payload.get("source") or "").lower()
    if payload.get("external_task_id") and (
        status in {"", "submitted", "queued", "pending", "processing", "running"}
        or source == "external_task_pending"
    ):
        checks.append({"key": "async_status", "status": "warn", "message": f"Asset task is still {status or source}."})
        return {
            "status": "warn",
            "score": 70.0,
            "flags": ["visual_qa_asset_processing"],
            "checks": checks,
            "metrics": {"size_bytes": size_bytes},
            "inspected_at": _now_iso(),
        }
    if size_bytes == 0:
        checks.append({"key": "file_size", "status": "fail", "message": "Asset file is empty."})
        return {"status": "fail", "score": 0.0, "flags": ["visual_qa_empty_file"], "checks": checks, "inspected_at": _now_iso()}

    metrics: dict[str, Any] = {"size_bytes": size_bytes}
    if asset_type in {"image", "storyboard_frame"}:
        metrics.update(_image_metrics(path))
        if size_bytes < 512:
            checks.append({"key": "placeholder_size", "status": "fail", "message": "Image is placeholder-sized."})
            flags.append("visual_qa_placeholder")
            score -= 70
        if metrics.get("decode_error"):
            checks.append({"key": "image_decode", "status": "fail", "message": metrics["decode_error"]})
            flags.append("visual_qa_decode_error")
            score -= 80
        width = metrics.get("width")
        height = metrics.get("height")
        if width == 1 and height == 1:
            checks.append({"key": "image_dimensions", "status": "fail", "message": "Image is 1x1 placeholder."})
            flags.append("visual_qa_placeholder")
            score -= 80
        expected = _parse_ratio(expected_ratio or payload.get("aspect_ratio"))
        actual = metrics.get("aspect_ratio")
        if expected and actual and abs(float(actual) - expected) / expected > 0.18:
            checks.append(
                {
                    "key": "aspect_ratio",
                    "status": "warn",
                    "message": f"Aspect ratio mismatch: expected {round(expected, 4)}, got {actual}.",
                }
            )
            flags.append("visual_qa_aspect_mismatch")
            score -= 15
        if metrics.get("dynamic_range") is not None and metrics["dynamic_range"] < 12:
            checks.append({"key": "visual_information", "status": "warn", "message": "Image has very low visual variation."})
            flags.append("visual_qa_low_information")
            score -= 25
        prompt = str(payload.get("prompt") or "").lower()
        if "text overlay" in prompt and "no text overlay" not in prompt:
            checks.append({"key": "text_overlay", "status": "warn", "message": "Prompt appears to allow text overlay."})
            flags.append("visual_qa_text_overlay_risk")
            score -= 10
    elif asset_type == "video":
        if status in {"submitted", "queued", "pending", "processing", "running"} or source == "external_task_pending":
            checks.append({"key": "async_status", "status": "warn", "message": f"Video task is still {status or source}."})
            flags.append("visual_qa_video_processing")
            score -= 30
        elif size_bytes < 1024:
            checks.append({"key": "video_size", "status": "fail", "message": "Completed video is too small to be valid."})
            flags.append("visual_qa_empty_video")
            score -= 80
        elif not _has_mp4_signature(path):
            checks.append({"key": "video_header", "status": "warn", "message": "Video header could not be recognized as MP4/MOV."})
            flags.append("visual_qa_video_header_unverified")
            score -= 20
    if not checks:
        checks.append({"key": "basic_media", "status": "pass", "message": "Basic local media QA passed."})
    fail_count = sum(1 for check in checks if check["status"] == "fail")
    warn_count = sum(1 for check in checks if check["status"] in {"warn", "manual_review"})
    status = "fail" if fail_count else "warn" if warn_count else "pass"
    return {
        "status": status,
        "score": max(0.0, round(score, 2)),
        "flags": sorted(set(flags)),
        "checks": checks,
        "metrics": metrics,
        "inspected_at": _now_iso(),
    }


def inspect_extracted_video_frames(
    *,
    frame_uris: list[str] | None,
    social_review_contract: dict | None = None,
    shot_plan: list[dict] | None = None,
) -> dict[str, Any]:
    frame_uris = [str(uri) for uri in (frame_uris or []) if str(uri).strip()]
    social_review_contract = social_review_contract or {}
    shot_plan = [dict(item) for item in (shot_plan or []) if isinstance(item, dict)]

    checks: list[dict[str, Any]] = []
    flags: list[str] = []
    score = 100.0
    required_checks = {str(item).strip() for item in (social_review_contract.get("required_checks") or []) if str(item).strip()}
    unusable_frame_reasons: list[str] = []

    required_review_copy = {
        "first_frame_clarity": (
            "visual_qa_first_frame_clarity_check",
            "Review the first sampled frame for immediate product clarity and hook readability.",
        ),
        "continuity": (
            "visual_qa_continuity_frame_check",
            "Review sampled frames for continuity across product appearance, scale, and scene transitions.",
        ),
        "product_truth": (
            "visual_qa_product_truth_frame_check",
            "Review sampled frames to confirm the product depiction stays truthful to the submitted item.",
        ),
        "cta_clarity": (
            "visual_qa_cta_clarity_frame_check",
            "Review late sampled frames to confirm the CTA moment is clear and legible.",
        ),
    }

    if not frame_uris:
        checks.append(
            {
                "key": "frame_sequence",
                "status": "manual_review",
                "message": "Completed video has no extracted frames; review after frame sampling.",
            }
        )
        flags.append("visual_qa_needs_frame_review")
        score -= 10
    else:
        for uri in frame_uris:
            frame_qa = inspect_visual_asset(asset_type="image", uri=uri, payload={})
            if str(frame_qa.get("status") or "") == "fail":
                unusable_frame_reasons.append(f"{Path(uri).name}:asset_status=fail")
                continue
            for frame_flag in frame_qa.get("flags") or []:
                if str(frame_flag) in {
                    "visual_qa_placeholder",
                    "visual_qa_decode_error",
                    "visual_qa_empty_file",
                    "visual_qa_missing_file",
                    "visual_qa_missing_uri",
                }:
                    unusable_frame_reasons.append(f"{Path(uri).name}:{frame_flag}")
                    break
        if unusable_frame_reasons:
            checks.append(
                {
                    "key": "frame_sequence_quality",
                    "status": "manual_review",
                    "message": "Extracted frames are missing, empty, or placeholder-like; resample or review manually.",
                    "details": unusable_frame_reasons[:3],
                }
            )
            flags.extend(["visual_qa_needs_frame_review", "visual_qa_unusable_frame_sequence"])
            score -= 10
        else:
            checks.append(
                {
                    "key": "frame_sequence",
                    "status": "pass",
                    "message": f"Frame sequence available with {len(frame_uris)} sampled frames.",
                }
            )

    for required_check in sorted(required_checks):
        review_copy = required_review_copy.get(required_check)
        if not review_copy:
            continue
        flag, message = review_copy
        checks.append(
            {
                "key": required_check,
                "status": "manual_review",
                "message": message,
            }
        )
        flags.append(flag)
        score -= 5

    if shot_plan:
        checks.append(
            {
                "key": "shot_plan_continuity",
                "status": "manual_review",
                "message": "Review sampled frames against shot intent and product continuity constraints.",
            }
        )
        flags.append("visual_qa_shot_plan_frame_check")
        score -= 5

    has_manual_review = any(check["status"] == "manual_review" for check in checks)
    status = "warn" if has_manual_review else "pass"
    return {
        "status": status,
        "score": max(0.0, round(score, 2)),
        "flags": sorted(set(flags)),
        "checks": checks,
        "inspected_at": _now_iso(),
        "frame_count": len(frame_uris),
        "first_frame_uri": frame_uris[0] if frame_uris else None,
    }

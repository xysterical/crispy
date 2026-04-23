from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from app.core.config import get_settings


MAX_FILES = 10
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024
MAX_TOTAL_SIZE_BYTES = 200 * 1024 * 1024

SKU_EXTENSIONS = {".csv", ".xlsx"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v"}


def _safe_name(name: str) -> str:
    return Path(name).name.replace(" ", "_")


def _parse_csv_bytes(data: bytes) -> list[dict]:
    text = data.decode("utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict] = []
    for idx, row in enumerate(reader):
        if idx >= 200:
            break
        rows.append({k: (v or "").strip() for k, v in row.items()})
    return rows


def _parse_xlsx_bytes(data: bytes) -> list[dict]:
    try:
        import openpyxl  # type: ignore
    except Exception:
        raise RuntimeError("openpyxl_not_installed")
    workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    sheet = workbook.active
    rows = list(sheet.iter_rows(min_row=1, max_row=201, values_only=True))
    if not rows:
        return []
    headers = [str(item) if item is not None else "" for item in rows[0]]
    parsed: list[dict] = []
    for row in rows[1:]:
        parsed.append({headers[idx]: row[idx] for idx in range(min(len(headers), len(row)))})
    return parsed


def _extract_video_frame_placeholders(run_id: str, variant: str, count: int = 3) -> list[str]:
    settings = get_settings()
    frame_dir = settings.assets_dir / run_id / "input_frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    frame_paths = []
    try:
        from PIL import Image  # type: ignore
    except Exception:
        Image = None  # type: ignore
    for idx in range(count):
        path = frame_dir / f"{variant}_frame_{idx + 1}.png"
        if Image is not None:
            img = Image.new("RGB", (720, 1280), color=(242, 246, 251))
            img.save(path, format="PNG")
        else:
            path.write_bytes(b"")
        frame_paths.append(str(path))
    return frame_paths


def process_uploaded_payloads(run_id: str, uploads: list[dict[str, Any]]) -> tuple[dict, list[dict]]:
    if len(uploads) > MAX_FILES:
        raise ValueError(f"too many files; max={MAX_FILES}")

    settings = get_settings()
    input_dir = settings.assets_dir / run_id / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    total_size = 0
    sku_summary: list[dict] = []
    sample_images: list[dict] = []
    sample_videos: list[dict] = []
    file_entries: list[dict] = []
    artifacts: list[dict] = []

    for item in uploads:
        filename = _safe_name(item["filename"])
        content = item["content"]
        content_type = item.get("content_type")
        size = len(content)
        total_size += size
        if size > MAX_FILE_SIZE_BYTES:
            raise ValueError(f"file too large: {filename} max={MAX_FILE_SIZE_BYTES}")
        if total_size > MAX_TOTAL_SIZE_BYTES:
            raise ValueError(f"total upload too large; max={MAX_TOTAL_SIZE_BYTES}")

        path = input_dir / filename
        path.write_bytes(content)
        ext = path.suffix.lower()
        entry = {
            "filename": filename,
            "content_type": content_type,
            "size_bytes": size,
            "uri": str(path),
            "extension": ext,
        }
        file_entries.append(entry)
        artifacts.append({"type": "input_file", "uri": str(path), "payload": entry})

        if ext in SKU_EXTENSIONS:
            try:
                parsed_rows = _parse_csv_bytes(content) if ext == ".csv" else _parse_xlsx_bytes(content)
                sku_summary.extend(parsed_rows[:100])
            except Exception as exc:
                sku_summary.append({"filename": filename, "parse_error": str(exc)})
        elif ext in IMAGE_EXTENSIONS:
            sample_images.append(entry)
        elif ext in VIDEO_EXTENSIONS:
            frames = _extract_video_frame_placeholders(run_id, Path(filename).stem, count=3)
            sample_videos.append({**entry, "frame_placeholders": frames, "duration_seconds": 15.0})
            for frame_path in frames:
                artifacts.append(
                    {
                        "type": "input_video_frame",
                        "uri": frame_path,
                        "payload": {"source_video": str(path), "frame_uri": frame_path},
                    }
                )

    summary = {
        "files": file_entries,
        "sku_summary": sku_summary,
        "sample_images": sample_images,
        "sample_videos": sample_videos,
    }
    return summary, artifacts

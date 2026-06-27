from __future__ import annotations

import subprocess
from pathlib import Path


def _ffmpeg_exe() -> str | None:
    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _clear_frame_outputs(output_dir: Path, prefix: str) -> None:
    for path in output_dir.glob(f"{prefix}_frame_*.png"):
        path.unlink(missing_ok=True)
    for path in output_dir.glob(f"{prefix}_fallback_frame_*.png"):
        path.unlink(missing_ok=True)


def _write_frame_placeholders(output_dir: Path, prefix: str, count: int) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image  # type: ignore
    except Exception:
        Image = None  # type: ignore
    paths: list[str] = []
    for idx in range(count):
        path = output_dir / f"{prefix}_frame_{idx + 1}.png"
        if Image is None:
            path.write_bytes(b"")
        else:
            # Use a 1x1 image so downstream QA can reliably recognize fallback frames as placeholders.
            Image.new("RGB", (1, 1), color=(255, 255, 255)).save(path, format="PNG")
        paths.append(str(path))
    return paths


def sample_video_frames(*, video_path: Path, output_dir: Path, prefix: str, count: int = 3) -> list[str]:
    ffmpeg = _ffmpeg_exe()
    if not ffmpeg:
        return _write_frame_placeholders(output_dir, prefix, count)

    output_dir.mkdir(parents=True, exist_ok=True)
    _clear_frame_outputs(output_dir, prefix)
    output_pattern = output_dir / f"{prefix}_frame_%03d.png"
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video_path),
        "-vf",
        "fps=1,scale='min(1200,iw)':-2",
        "-frames:v",
        str(count),
        str(output_pattern),
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45)
    except Exception:
        return _write_frame_placeholders(output_dir, prefix, count)

    frames = sorted(output_dir.glob(f"{prefix}_frame_*.png"))[:count]
    if not frames:
        return _write_frame_placeholders(output_dir, prefix, count)
    if len(frames) < count:
        fallback = _write_frame_placeholders(output_dir, f"{prefix}_fallback", count - len(frames))
        return [str(path) for path in frames] + fallback
    return [str(path) for path in frames]


def extract_last_video_frame(*, video_path: Path, output_path: Path) -> str | None:
    ffmpeg = _ffmpeg_exe()
    if not ffmpeg or not video_path.exists():
        return None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-sseof",
        "-0.1",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        str(output_path),
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    except Exception:
        return None
    return str(output_path) if output_path.exists() else None


def stitch_video_files(*, video_paths: list[Path], output_path: Path) -> str | None:
    ffmpeg = _ffmpeg_exe()
    if not ffmpeg or not video_paths or any(not path.exists() for path in video_paths):
        return None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    list_path = output_path.with_suffix(".concat.txt")
    def concat_line(path: Path) -> str:
        safe = str(path.resolve()).replace("'", "'\\''")
        return f"file '{safe}'\n"

    list_path.write_text(
        "".join(concat_line(path) for path in video_paths),
        encoding="utf-8",
    )
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_path),
        "-c",
        "copy",
        str(output_path),
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    except Exception:
        return None
    return str(output_path) if output_path.exists() else None

from __future__ import annotations

import subprocess
from pathlib import Path


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
    try:
        import imageio_ffmpeg  # type: ignore

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
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

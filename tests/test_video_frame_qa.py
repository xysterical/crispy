from pathlib import Path
import builtins
import types

import pytest

from app.services.intake_assets import process_uploaded_payloads
from app.services.video_frames import sample_video_frames


def test_sample_video_frames_falls_back_for_invalid_video(tmp_path):
    fake = tmp_path / "fake.mp4"
    fake.write_bytes(b"not a real video")
    frames = sample_video_frames(
        video_path=fake,
        output_dir=tmp_path / "frames",
        prefix="fake",
        count=3,
    )
    assert len(frames) == 3
    assert all(Path(frame).exists() for frame in frames)


def test_sample_video_frames_extracts_real_frames_when_ffmpeg_available(tmp_path):
    try:
        import imageio_ffmpeg  # type: ignore
        import subprocess

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        pytest.skip(f"ffmpeg unavailable: {exc}")
    video_path = tmp_path / "sample.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=96x96:rate=2:duration=2",
            "-pix_fmt",
            "yuv420p",
            str(video_path),
        ],
        check=True,
        timeout=45,
    )
    frames = sample_video_frames(
        video_path=video_path,
        output_dir=tmp_path / "real_frames",
        prefix="real",
        count=3,
    )
    assert len(frames) == 3
    assert all(Path(frame).exists() for frame in frames)


def test_sample_video_frames_fallback_still_returns_paths_without_pil(tmp_path, monkeypatch):
    fake = tmp_path / "fake.mp4"
    fake.write_bytes(b"not a real video")
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "PIL":
            raise ImportError("PIL unavailable")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    frames = sample_video_frames(
        video_path=fake,
        output_dir=tmp_path / "frames_no_pil",
        prefix="fake",
        count=3,
    )

    assert len(frames) == 3
    assert all(Path(frame).exists() for frame in frames)


def test_sample_video_frames_clears_stale_prefix_frames_before_sampling(tmp_path, monkeypatch):
    output_dir = tmp_path / "stale_frames"
    output_dir.mkdir(parents=True, exist_ok=True)
    stale = output_dir / "same_frame_001.png"
    stale.write_bytes(b"stale")
    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"fake-but-unused")

    fake_ffmpeg = types.SimpleNamespace(get_ffmpeg_exe=lambda: "ffmpeg")
    monkeypatch.setitem(__import__("sys").modules, "imageio_ffmpeg", fake_ffmpeg)

    def fake_run(cmd, check, stdout, stderr, timeout):
        return None

    monkeypatch.setattr("app.services.video_frames.subprocess.run", fake_run)

    frames = sample_video_frames(
        video_path=video_path,
        output_dir=output_dir,
        prefix="same",
        count=3,
    )

    assert len(frames) == 3
    assert all(Path(frame).exists() for frame in frames)
    assert str(stale) not in frames
    assert not stale.exists()


def test_process_uploaded_payloads_keeps_duplicate_video_filenames_distinct():
    summary, artifacts = process_uploaded_payloads(
        "duplicate-video-names",
        [
            {"filename": "clip.mp4", "content_type": "video/mp4", "content": b"not a video one"},
            {"filename": "clip.mp4", "content_type": "video/mp4", "content": b"not a video two"},
        ],
    )

    videos = summary["sample_videos"]
    assert len(videos) == 2
    assert videos[0]["uri"] != videos[1]["uri"]
    assert set(videos[0]["frame_placeholders"]).isdisjoint(videos[1]["frame_placeholders"])
    assert all(Path(video["uri"]).exists() for video in videos)
    assert all(Path(frame).exists() for video in videos for frame in video["frame_placeholders"])
    assert len([item for item in artifacts if item["type"] == "input_video_frame"]) == 6

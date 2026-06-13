from pathlib import Path

import pytest

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

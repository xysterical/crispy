from __future__ import annotations

import base64
import io
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from app.data.models import PipelineRun, StageTask
from app.data.session import SessionLocal
from app.orchestrator.worker import worker
from app.providers.llm import GeneratedImage, ImageGenResult, StubProvider
from app.services.creative_specs import resolve_creative_specs
from app.services.intake_assets import process_uploaded_payloads
from app.services.marketplace_qa import inspect_marketplace_image
from app.services.runs import execute_next_queued_stage, runtime


def _run_worker_once() -> None:
    with SessionLocal() as db:
        execute_next_queued_stage(db)
        db.commit()


def _png_bytes(*, size: tuple[int, int] = (1200, 1200), product_box: tuple[int, int, int, int] | None = None, bg=(255, 255, 255)) -> bytes:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", size, bg)
    if product_box:
        draw = ImageDraw.Draw(image)
        draw.rectangle(product_box, fill=(35, 35, 35))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _write_png(path: Path, **kwargs) -> Path:
    path.write_bytes(_png_bytes(**kwargs))
    return path


class FakeMarketplaceProvider(StubProvider):
    def __init__(self) -> None:
        super().__init__("openai")
        self.last_image_request = None

    def generate_image(self, request, *, api_base_url=None, api_key=None, extra=None):
        self.last_image_request = request
        raw = _png_bytes(size=(2000, 2000), product_box=(360, 360, 1640, 1640))
        return ImageGenResult(
            model_used=request.model,
            images=[GeneratedImage(b64_json=base64.b64encode(raw).decode("ascii"))],
        )


def test_marketplace_preset_resolves_square_export_specs():
    specs = resolve_creative_specs("marketplace_main_image_pack")
    assert specs["asset_goal"] == "marketplace_main_image"
    assert specs["image_size"] == "1:1"
    assert specs["export_size_px"] == 2000
    assert specs["background_policy"] == "pure_white"
    assert "amazon" in specs["platform_targets"]


def test_marketplace_qa_catches_bad_images(tmp_path):
    tiny = _write_png(tmp_path / "tiny.png", size=(200, 200), product_box=(80, 80, 120, 120))
    nonwhite = _write_png(tmp_path / "nonwhite.png", size=(1200, 1200), product_box=(520, 520, 680, 680), bg=(230, 230, 230))
    low_fill = _write_png(tmp_path / "low_fill.png", size=(1200, 1200), product_box=(560, 560, 640, 640))
    good = _write_png(tmp_path / "good.png", size=(2000, 2000), product_box=(360, 360, 1640, 1640))
    specs = resolve_creative_specs("marketplace_main_image_pack")
    base_payload = {"reference_source_count": 1, "source": "url", "prompt": "no text overlay"}

    tiny_qa = inspect_marketplace_image(uri=str(tiny), payload=base_payload, creative_specs=specs)
    assert tiny_qa["status"] == "fail"
    assert "marketplace_resolution_low" in tiny_qa["flags"]

    nonwhite_qa = inspect_marketplace_image(uri=str(nonwhite), payload=base_payload, creative_specs=specs)
    assert nonwhite_qa["status"] == "fail"
    assert "marketplace_background_not_white" in nonwhite_qa["flags"]

    low_fill_qa = inspect_marketplace_image(uri=str(low_fill), payload=base_payload, creative_specs=specs)
    assert low_fill_qa["status"] == "fail"
    assert "product_fill_low" in low_fill_qa["flags"]

    placeholder_qa = inspect_marketplace_image(
        uri=str(good),
        payload={**base_payload, "source": "placeholder", "prompt": "text overlay allowed"},
        creative_specs=specs,
    )
    assert placeholder_qa["status"] == "fail"
    assert "marketplace_placeholder" in placeholder_qa["flags"]
    assert "marketplace_text_overlay_risk" in placeholder_qa["flags"]

    good_qa = inspect_marketplace_image(uri=str(good), payload=base_payload, creative_specs=specs)
    assert good_qa["status"] == "pass"
    assert good_qa["export_ready"] is True
    assert all(status == "pass" for status in good_qa["platform_readiness"].values())


def test_video_frame_extraction_caps_and_fallback(tmp_path):
    fake_summary, fake_artifacts = process_uploaded_payloads(
        "marketplace-fake-video",
        [{"filename": "fake.mp4", "content_type": "video/mp4", "content": b"not a video"}],
    )
    assert len(fake_summary["sample_videos"][0]["frame_placeholders"]) == 3
    assert len([item for item in fake_artifacts if item["type"] == "input_video_frame"]) == 3

    try:
        import imageio_ffmpeg  # type: ignore

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
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
    except Exception as exc:
        pytest.skip(f"ffmpeg unavailable for real frame extraction: {exc}")

    real_summary, _ = process_uploaded_payloads(
        "marketplace-real-video",
        [{"filename": "sample.mp4", "content_type": "video/mp4", "content": video_path.read_bytes()}],
    )
    frames = real_summary["sample_videos"][0]["frame_placeholders"]
    assert len(frames) == 3
    assert all(Path(frame).exists() for frame in frames)
    assert len(frames) <= 3


def test_marketplace_preflight_blocks_missing_media_and_explicit_no_reference_edit(client):
    specs = resolve_creative_specs("marketplace_main_image_pack")
    resp = client.post(
        "/runs/preflight",
        json={
            "pipeline_mode": "copy_image_only",
            "has_image_inputs": False,
            "has_video_inputs": False,
            "creative_specs": specs,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["severity"] == "error"
    assert "marketplace_main_image.reference_media" in [item["key"] for item in payload["checks"]]

    patch = client.patch(
        "/agent-configs/copy_image_agent",
        json={
            "image_provider_name": "openai",
            "image_model_name": "gpt-image-2",
            "extra": {"image_config": {"supports_reference_edit": False}},
        },
    )
    assert patch.status_code == 200
    resp = client.post(
        "/runs/preflight",
        json={
            "pipeline_mode": "copy_image_only",
            "has_image_inputs": True,
            "has_video_inputs": False,
            "creative_specs": specs,
        },
    )
    keys = [item["key"] for item in resp.json()["checks"]]
    assert "copy_image_generation.reference_edit" in keys
    assert resp.json()["severity"] == "error"


def test_marketplace_pipeline_mode_defaults_to_main_image_specs(client):
    resp = client.post(
        "/runs",
        json={
            "workspace_name": "w-market-mode",
            "project_name": "p-market-mode",
            "product_name": "ceramic mug",
            "product_code": "MUG-MODE-001",
            "industry_code": "home_goods",
            "campaign_name": "market-main-image-mode",
            "creative_preset": "custom",
            "creative_specs": {
                "image_size": "1:1",
                "video_size": "1:1",
                "resolution": "2000px",
                "video_duration_seconds": 5,
                "image_urls": ["https://cdn.example.com/reference/mug.png?sig=1"],
            },
            "pipeline_mode": "marketplace_main_image",
            "approval_mode": "semi_auto",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["pipeline_mode"] == "marketplace_main_image"
    assert body["creative_preset"] == "marketplace_main_image_pack"
    assert body["creative_specs"]["asset_goal"] == "marketplace_main_image"
    assert body["creative_specs"]["export_size_px"] == 2000


def test_marketplace_pipeline_mode_preflight_requires_reference_media(client):
    resp = client.post(
        "/runs/preflight",
        json={
            "pipeline_mode": "marketplace_main_image",
            "has_image_inputs": False,
            "has_video_inputs": False,
            "creative_specs": {},
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["severity"] == "error"
    assert "marketplace_main_image.reference_media" in [item["key"] for item in payload["checks"]]


def test_marketplace_run_generates_qa_and_export_zip(client, monkeypatch):
    fake_provider = FakeMarketplaceProvider()
    monkeypatch.setitem(runtime.providers._providers, "openai", fake_provider)
    image_bytes = _png_bytes(size=(1200, 1200), product_box=(260, 260, 940, 940))
    data = {
        "workspace_name": "w-market",
        "project_name": "p-market",
        "product_name": "ceramic mug",
        "product_code": "MUG-001",
        "industry_code": "home_goods",
        "campaign_name": "market-main-image",
        "creative_preset": "marketplace_main_image_pack",
        "creative_specs": json.dumps(resolve_creative_specs("marketplace_main_image_pack")),
        "pipeline_mode": "copy_image_only",
        "approval_mode": "semi_auto",
        "variant_count": "4",
        "business_context": '{"target_audience":"gift shoppers","primary_cta":"View Product"}',
        "category_tags": '["home_goods","mug"]',
    }
    files = [("files", ("mug.png", io.BytesIO(image_bytes), "image/png"))]
    resp = client.post("/runs/rich", data=data, files=files)
    assert resp.status_code == 200
    run_id = resp.json()["id"]

    _run_worker_once()
    run = client.get(f"/runs/{run_id}").json()
    intake = next(task for task in run["stage_tasks"] if task["stage_name"] == "intake")
    assert intake["output_payload"]["visual_identity"]["best_reference_images"]
    assert intake["output_payload"]["visual_identity"]["source_media_count"]["images"] == 1
    client.post(f"/runs/{run_id}/advance", json={"notes": "approve intake"})

    for stage in ["planning", "divergence", "copy_image_generation", "visual_quality_assessment", "evaluation_selection"]:
        _run_worker_once()
        run = client.get(f"/runs/{run_id}").json()
        task = next(item for item in run["stage_tasks"] if item["stage_name"] == stage)
        assert task["status"] == "waiting_review"
        if stage in {"copy_image_generation", "visual_quality_assessment"}:
            with SessionLocal() as db:
                run_model = db.get(PipelineRun, run_id)
                task_model = db.get(StageTask, task["id"])
                assert worker._should_marketplace_auto_approve(run_model, task_model) is True
        if stage != "evaluation_selection":
            client.post(f"/runs/{run_id}/advance", json={"notes": f"approve {stage}"})

    run = client.get(f"/runs/{run_id}").json()
    copy_task = next(task for task in run["stage_tasks"] if task["stage_name"] == "copy_image_generation")
    image_assets = copy_task["output_payload"]["image_assets"]
    assert {item["image_role"] for item in image_assets} >= {"compliance_master", "premium_white"}
    assert all(item["marketplace_qa"]["status"] == "pass" for item in image_assets), [
        item["marketplace_qa"] for item in image_assets
    ]
    assert all(item["export_ready"] for item in image_assets)
    assert fake_provider.last_image_request is not None
    assert fake_provider.last_image_request.mode == "edit"
    assert fake_provider.last_image_request.reference_image_urls

    visual_task = next(task for task in run["stage_tasks"] if task["stage_name"] == "visual_quality_assessment")
    not_ready = [item for item in visual_task["output_payload"]["variant_summaries"] if not item["export_ready"]]
    assert not not_ready, not_ready

    deliverables = client.get(f"/runs/{run_id}/deliverables").json()
    image_deliverables = deliverables["deliverables"]["image_assets"]
    assert image_deliverables
    assert "platform_readiness" in image_deliverables[0]

    zip_resp = client.get(f"/runs/{run_id}/deliverables.zip")
    assert zip_resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as zf:
        names = zf.namelist()
        assert "qa_report.json" in names
        assert any(name.endswith(".png") for name in names)
        report = json.loads(zf.read("qa_report.json"))
    assert report["exported_count"] >= 1
    assert report["visual_identity"]["product_type"] == "ceramic mug"

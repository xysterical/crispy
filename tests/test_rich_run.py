from __future__ import annotations

import io

from app.data.session import SessionLocal
from app.services.runs import execute_next_queued_stage


def _run_worker_once() -> None:
    with SessionLocal() as db:
        execute_next_queued_stage(db)
        db.commit()


def test_runs_rich_accepts_multimodal_inputs(client):
    csv_content = "sku,price,feature\nA1,19.9,odor-control\nA2,24.9,time-saving\n".encode("utf-8")
    files = [
        ("files", ("sku.csv", io.BytesIO(csv_content), "text/csv")),
        ("files", ("sample.jpg", io.BytesIO(b"fakeimage"), "image/jpeg")),
        ("files", ("sample.mp4", io.BytesIO(b"fakevideo"), "video/mp4")),
    ]
    data = {
        "workspace_name": "w-rich",
        "project_name": "p-rich",
        "product_name": "pet wipes rich",
        "product_code": "PWR-001",
        "industry_code": "pet_care",
        "campaign_name": "meta-rich",
        "creative_preset": "meta_square_5s",
        "pipeline_mode": "copy_image_only",
        "business_context": '{"target_audience":"pet owners","primary_cta":"Shop Now","campaign_objective":"conversions"}',
        "category_tags": '["pet_care","hygiene"]',
        "url_references": '["https://example.com/product-page"]',
        "enable_research": "false",
    }
    resp = client.post("/runs/rich", data=data, files=files)
    assert resp.status_code == 200
    run_json = resp.json()
    run_id = run_json["id"]
    assert run_json["pipeline_mode"] == "copy_image_only"

    _run_worker_once()
    run_view = client.get(f"/runs/{run_id}").json()
    intake_task = [t for t in run_view["stage_tasks"] if t["stage_name"] == "intake"][0]
    assert intake_task["status"] == "waiting_review"
    assert len(intake_task["output_payload"]["sku_summary"]) >= 1
    assert len(intake_task["output_payload"]["url_references"]) == 1
    assert len(intake_task["output_payload"]["video_references"]) == 1
    assert "asset_media_summary" in intake_task["output_payload"]


def test_runs_rich_rejects_too_many_files(client):
    files = [("files", (f"f{i}.txt", io.BytesIO(b"x"), "text/plain")) for i in range(11)]
    data = {
        "workspace_name": "w-rich2",
        "project_name": "p-rich2",
        "product_name": "pet rich2",
        "product_code": "PR2-001",
        "industry_code": "pet_care",
        "campaign_name": "meta-rich2",
        "creative_preset": "meta_square_5s",
    }
    resp = client.post("/runs/rich", data=data, files=files)
    assert resp.status_code == 400
    assert "too many files" in resp.text


def test_rich_run_accepts_tiktok_shop_video_style(client):
    resp = client.post(
        "/runs/rich",
        data={
            "workspace_name": "tiktok_rich_ws",
            "project_name": "tiktok_rich_project",
            "product_name": "portable blender",
            "product_code": "TT-RICH-001",
            "industry_code": "kitchen",
            "campaign_name": "tiktok-rich",
            "pipeline_mode": "tiktok_shop_video",
            "creative_preset": "tiktok_shop_conversion_12s",
            "creative_specs": '{"video_size":"9:16","video_duration_seconds":12,"tiktok_video_style":"shop_account_content"}',
            "manual_research_brief": "Show daily smoothie prep for busy buyers.",
            "enable_research": "true",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["pipeline_mode"] == "tiktok_shop_video"
    assert body["creative_specs"]["tiktok_video_style"] == "shop_account_content"
    assert body["enable_research"] is False


def test_rich_run_accepts_memory_selection(client):
    resp = client.post(
        "/runs/rich",
        data={
            "workspace_name": "memory_selection_rich_ws",
            "project_name": "memory_selection_rich_project",
            "product_name": "portable blender",
            "product_code": "MEM-RICH-001",
            "industry_code": "kitchen",
            "campaign_name": "memory-selection-rich",
            "pipeline_mode": "copy_image_only",
            "creative_preset": "custom",
            "creative_specs": '{"image_size":"1:1","video_size":"1:1","resolution":"720p","video_duration_seconds":5}',
            "memory_selection": '{"mode":"none","include_ids":[],"exclude_ids":[]}',
        },
        files=[("files", ("sample.jpg", io.BytesIO(b"fakeimage"), "image/jpeg"))],
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["memory_selection"]["mode"] == "none"

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

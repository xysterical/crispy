from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine

from app.data.base import Base
from app.data.session import SessionLocal
from app.orchestrator.state_machine import stage_plan_for
from app.services.runs import execute_next_queued_stage


def _run_worker_once() -> None:
    with SessionLocal() as db:
        execute_next_queued_stage(db)
        db.commit()


def test_dashboard_data_source_switch(client):
    run_resp = client.post(
        "/runs",
        json={
            "workspace_name": "switch_w",
            "project_name": "switch_p",
            "product_name": "switch_product",
            "product_code": "SW-001",
            "industry_code": "pet_accessories",
            "campaign_name": "switch_campaign",
            "creative_preset": "meta_square_5s",
            "pipeline_mode": "copy_image_only",
            "business_context": {"target_audience": "pet owners"},
        },
    )
    assert run_resp.status_code == 200
    run_id = run_resp.json()["id"]

    active_before = client.get("/dashboard/data-sources")
    assert active_before.status_code == 200
    active_url = active_before.json()["active_url"]

    alt_db_path = Path("test_alt_dashboard.db").resolve()
    alt_url = f"sqlite:///{alt_db_path}"
    alt_engine = create_engine(alt_url, future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=alt_engine)
    alt_engine.dispose()
    try:
        select_alt = client.post("/dashboard/data-sources/select", json={"url": alt_url})
        assert select_alt.status_code == 200
        assert select_alt.json()["active_url"] == alt_url

        runs_alt = client.get("/runs")
        assert runs_alt.status_code == 200
        assert runs_alt.json() == []

        select_back = client.post("/dashboard/data-sources/select", json={"url": active_url})
        assert select_back.status_code == 200
        runs_back = client.get("/runs")
        assert runs_back.status_code == 200
        assert any(item["id"] == run_id for item in runs_back.json())
    finally:
        client.post("/dashboard/data-sources/select", json={"url": active_url})
        if alt_db_path.exists():
            alt_db_path.unlink()


def test_artifacts_endpoint_filters_generated_outputs(client):
    create_resp = client.post(
        "/runs",
        json={
            "workspace_name": "assets_w",
            "project_name": "assets_p",
            "product_name": "dog leash",
            "product_code": "DL-TEST-001",
            "industry_code": "pet_accessories",
            "campaign_name": "assets_campaign",
            "creative_preset": "meta_square_5s",
            "pipeline_mode": "copy_image_only",
            "business_context": {"target_audience": "dog owners", "primary_cta": "Shop Now"},
        },
    )
    assert create_resp.status_code == 200
    run_id = create_resp.json()["id"]

    for stage in stage_plan_for("copy_image_only"):
        _run_worker_once()
        if stage != stage_plan_for("copy_image_only")[-1]:
            ok = client.post(f"/runs/{run_id}/advance", json={"notes": "ok"})
            assert ok.status_code == 200

    resp = client.get("/artifacts", params={"pipeline_mode": "copy_image_only", "sort_by": "score"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total"] > 0
    assert len(payload["items"]) > 0
    assert all(item["artifact_type"] != "input_file" for item in payload["items"])
    assert any(item["artifact_type"] == "generated_image" for item in payload["items"])

    search_resp = client.get("/artifacts", params={"q": run_id, "pipeline_mode": "copy_image_only"})
    assert search_resp.status_code == 200
    searched = search_resp.json()["items"]
    assert all(item["run_id"] == run_id for item in searched)

    by_code_resp = client.get("/artifacts", params={"product_code": "DL-TEST-001"})
    assert by_code_resp.status_code == 200
    by_code_items = by_code_resp.json()["items"]
    assert len(by_code_items) > 0
    assert all(item["product_code"] == "DL-TEST-001" for item in by_code_items)


def test_dashboard_run_detail_contains_trace_board_and_variant_collapse(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.text
    assert "id=\"agent-trace-board\"" in html
    assert "trace-event-expanded" in html
    assert "bindTracePayloadToggles" in html
    assert "variant-board-toggle" in html
    assert "variant_board_collapsed" in html


def test_dashboard_create_run_has_accordion_sections(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.text
    assert "Product & Assets" in html
    assert "Platform & Creative" in html
    assert "Campaign & Targeting" in html
    assert "Research & Context" in html
    assert "quick-fill-preset" in html
    assert "template-selector" in html
    assert "mode-guided" in html
    assert "mode-expert" in html
    assert "file-drop-zone" in html


def test_create_run_dashboard_has_tiktok_video_style_control(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.text
    assert 'id="tiktok_video_style"' in html
    assert "TikTok Video Style" in html
    assert "direct_response_ad" in html
    assert "shop_account_content" in html
    assert "spec.tiktok_video_style" in html


def test_dashboard_create_run_labels_pipeline_and_specs_clearly(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.text

    assert "Run Template:" in html
    assert "Creative Template:" not in html
    assert "Creative Specs Preset" in html
    assert "'copy_image_only': ['field-image-size']" in html
    assert "'dtc_site_image': ['field-image-size', 'field-dtc-site-surface']" in html
    assert "'marketplace_main_image': ['field-image-size']" in html
    assert "DTC Site Image" in html
    assert "dtc_site_image_pack" in html
    assert 'id="dtc_site_surface"' in html
    assert "DTC Site Surface" in html
    assert "homepage_hero" in html
    assert "pdp_primary" in html
    assert "Studio Main Image" in html
    assert "marketplace_main_image_pack" in html
    assert 'if (m === "marketplace_main_image") return "Studio Main Image";' in html
    assert 'if (typeof refreshPipelineFields === "function") refreshPipelineFields();' in html
    assert '<select id="channel"' in html
    assert "Meta Ads" in html

    modes = {item["mode"]: item for item in client.get("/pipeline-modes").json()}
    assert modes["dtc_site_image"]["display_name"] == "DTC Site Image"
    assert modes["video_only"]["display_name"] == "Copy + Video"
    assert modes["full_multimodal"]["display_name"] == "Full Multimodal"
    assert modes["marketplace_main_image"]["display_name"] == "Studio Main Image"


def test_dashboard_variant_detail_renders_review_hints_section(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.text
    assert "Review Hints" in html
    assert "qSummary.review_hints" in html

from __future__ import annotations

import io
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


def _patch_valid_generated_images(monkeypatch):
    def fake_materialize_generated_image(_selected):
        from PIL import Image

        image = Image.new("RGB", (200, 200))
        for x in range(200):
            for y in range(200):
                image.putpixel((x, y), ((x * 3) % 255, (y * 5) % 255, ((x + y) * 2) % 255))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue(), "b64_json"

    monkeypatch.setattr("app.services.runs.runtime._materialize_generated_image", fake_materialize_generated_image)


def test_dashboard_pages_share_global_rail(client):
    pages = {
        "/dashboard": "/dashboard",
        "/dashboard/data": "/dashboard/data",
        "/dashboard/calendar": "/dashboard/calendar",
        "/dashboard/assets": "/dashboard/assets",
        "/dashboard/gm-review": "/dashboard/gm-review",
        "/dashboard/shop-analysis": "/dashboard/shop-analysis",
        "/dashboard/personas": "/dashboard/personas",
        "/dashboard/agent-apis": "/dashboard/agent-apis",
    }
    for path, active_href in pages.items():
        resp = client.get(path)
        assert resp.status_code == 200
        assert 'class="global-rail"' in resp.text
        assert f'class="rail-link active" href="{active_href}"' in resp.text
        assert "Back to Dashboard" not in resp.text


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


def test_artifacts_endpoint_filters_generated_outputs(client, monkeypatch):
    _patch_valid_generated_images(monkeypatch)
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
    assert "function renderReviewChecklist(run)" in html
    assert "function currentReviewTask(run)" in html
    assert "function summarizeVariants(rows)" in html
    assert "function copyImageReviewRows(payload)" in html
    assert "function videoReviewRows(payload)" in html
    assert "function visualQualityReviewRows(payload)" in html
    assert "function focusVariantFromChecklist(variantId)" in html
    assert "function renderChecklistItem(item)" in html
    assert "review-checklist-sublist" in html
    assert "review-checklist-thumb" in html
    assert "review-checklist-video" in html
    assert "Open in board" in html
    assert 'detail: [item.hook, item.message].filter(Boolean).join(" - "),' in html
    assert "items.push(summarizeVariants(payload.variants));" in html
    assert "items.push(copyImageReviewRows(payload));" in html
    assert "items.push(videoReviewRows(payload));" in html
    assert "items.push(visualQualityReviewRows(payload));" in html
    assert "Model summary: ${payload.model_summary}" in html
    assert "Variants reviewed:" in html
    assert "Assets checked:" in html
    assert "Review checklist" in html
    assert "${renderReviewChecklist(run)}" in html
    assert "function renderFailureReasons(info)" in html
    assert "Failure reasons" in html
    assert "media_gate_decode_error" in html
    assert "Copy/Image local media gate could not decode the generated media." in html
    assert "Generated media could not be decoded." in html
    assert "extractFailureFlags(info.detail)" in html
    assert "function providerSummary(run)" in html
    assert "currentStageTask(run)?.metadata_json?.resolved_api" in html
    assert "run fallback:" in html
    assert "provider/model: ${esc(providerSummary(run))}" in html
    assert "function failedMediaAsset(asset)" in html
    assert "winner?.recommended_action" in html
    assert "source === \"generation_error\"" in html
    assert "_generation_error." in html
    assert ".status-explainer-main { display: block; text-align: center; }" in html
    assert ".status-explainer-action { display: inline-flex; margin-top: 8px;" in html
    assert "white-space: nowrap;" in html
    assert ".status-explainer ol { margin: 10px 0 0 0; padding-left: 22px;" in html


def test_dashboard_create_run_has_accordion_sections(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.text
    assert "Product & Assets" in html
    assert "Product Name (required)" in html
    assert "Product Category (required)" in html
    assert "Campaign (required)" in html
    assert '<input id="product_name" value="" placeholder="Enter product name" required />' in html
    assert '<input id="project_name" list="category-list" value="" placeholder="e.g. summer-collection" required />' in html
    assert '<input id="campaign_name" value="" placeholder="e.g. spring-launch" required />' in html
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


def test_create_run_dashboard_has_creative_risk_control(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.text
    assert 'id="creative_risk_level"' in html
    assert "Creative Risk" in html
    assert "Bold Metaphor" in html
    assert "Wildcard" in html
    assert "spec.creative_risk_level = document.getElementById('creative_risk_level').value || 'safe';" in html
    assert "document.getElementById('creative_risk_level').value = lastProductConfig.creative_specs.creative_risk_level || 'safe';" in html
    assert "'creative_risk_level'" in html


def test_dashboard_storyboard_candidate_control_is_advanced_and_persisted(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.text

    assert 'id="field-storyboard-candidate-count" style="display:none;"' in html
    assert "Storyboard Candidates" in html
    assert "storyboard_candidate_count" in html
    assert "applyLastConfig()" in html
    assert "collectFormConfig()" in html
    assert "document.getElementById('storyboard_candidate_count').value" in html
    assert "'storyboard_candidate_count'" in html
    assert "storyboard_candidate_count: p.storyboard_candidate_count" in html
    assert "storyboard_candidate_count: parseInt(document.getElementById('storyboard_candidate_count').value, 10) || 1" in html
    assert "tiktok_video_style: p.tiktok_video_style" in html
    assert "site_surface: p.site_surface" in html
    assert "document.getElementById('dtc_site_surface').value = lastProductConfig.creative_specs.site_surface || 'pdp_primary';" in html
    assert "'dtc_site_surface'" in html
    assert "style.display = visible.includes('field-video-advanced') ? 'block' : 'none'" not in html


def test_dashboard_quick_fill_keeps_tiktok_system_preset_metadata(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.text
    assert "sys_tiktok_shop_conversion_12s" in html
    assert "tiktok_video_style: 'ugc_demo'" in html
    assert "platform: 'tiktok'" in html
    assert "creative_goal: 'shop_conversion_video'" in html


def test_dashboard_create_run_labels_pipeline_and_specs_clearly(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.text

    assert "Run Template:" in html
    assert "Creative Template:" not in html
    assert "Creative Specs Preset" in html
    assert "'copy_image_only': ['field-image-size', 'field-image-reference-urls', 'field-image-official-fallback']" in html
    assert "'dtc_site_image': ['field-image-size', 'field-image-reference-urls', 'field-image-official-fallback', 'field-dtc-site-surface']" in html
    assert "'marketplace_main_image': ['field-image-size', 'field-image-reference-urls', 'field-image-official-fallback']" in html
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
    assert 'id="generate_audio"' in html
    assert 'id="return_last_frame"' in html
    assert 'id="seed"' in html
    assert 'id="video_reference_urls"' in html
    assert 'id="audio_reference_urls"' in html
    assert 'id="video_first_frame_url"' in html
    assert 'id="video_last_frame_url"' in html
    assert "4-60 seconds; runs over 15 seconds are generated as stitched segments" in html
    assert "Up to 9 reference images" in html
    assert "First/last frame mode cannot be combined with video or audio references" in html
    assert "validateCreateRunForm" in html
    assert "buildImageWithRoles" in html

    modes = {item["mode"]: item for item in client.get("/pipeline-modes").json()}
    assert modes["dtc_site_image"]["display_name"] == "DTC Site Image"
    assert modes["video_only"]["display_name"] == "Copy + Video"
    assert modes["full_multimodal"]["display_name"] == "Full Multimodal"
    assert modes["marketplace_main_image"]["display_name"] == "Studio Main Image"


def test_create_run_dashboard_renders_failure_details(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.text

    assert "createRunErrorDetailHtml" in html
    assert "No failure detail returned by the server." in html
    assert "JSON.parse(text)" in html
    assert "renderCreateRunMessage('error', 'Run creation failed.', createRunErrorDetailHtml(detail))" in html


def test_create_run_dashboard_opens_created_run_detail(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.text

    assert "const createdRunId = result.data.id;" in html
    assert "selectRun(createdRunId).then(refreshAfterCreate).catch(refreshAfterCreate)" in html
    assert "detailPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });" in html


def test_dashboard_variant_detail_renders_review_hints_section(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.text
    assert "Review Hints" in html
    assert "qSummary.review_hints" in html


def test_dashboard_image_retry_is_thumbnail_overlay(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.text
    assert "function retryVariantImage(event, runId, variantId)" in html
    assert "window.confirm(`Retry image generation for ${variantId}?`)" in html
    assert "function waitForRetriedImage(runId, variantId)" in html
    assert "function preferredImageAsset(images)" in html
    assert "Image retry completed for ${variantId}." in html
    assert "Image processing" in html
    assert "Image failed" in html
    assert "thumb-wrap" in html
    assert "image-retry-btn" in html
    assert "retry-spinner" in html
    assert '<button onclick="retryVariantImage' not in html

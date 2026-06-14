# tests/test_preflight_inline.py

from __future__ import annotations

import io


def test_product_config_hint_returns_none_for_unknown(client):
    resp = client.get("/product-config-hint?product_code=NOEXIST")
    assert resp.status_code == 200
    assert resp.json() is None


def test_product_config_hint_after_run(client):
    # create a run first
    run_resp = client.post(
        "/runs",
        json={
            "workspace_name": "hint_ws",
            "project_name": "hint_project",
            "product_name": "hint_product",
            "product_code": "HINT-001",
            "industry_code": "pet",
            "campaign_name": "hint_camp",
            "creative_preset": "meta_square_5s",
            "pipeline_mode": "video_only",
            "approval_mode": "semi_auto",
        },
    )
    assert run_resp.status_code == 200

    hint_resp = client.get("/product-config-hint?product_code=HINT-001")
    assert hint_resp.status_code == 200
    hint = hint_resp.json()
    assert hint is not None
    assert hint["product_code"] == "HINT-001"
    assert hint["pipeline_mode"] == "video_only"
    assert hint["approval_mode"] == "semi_auto"


def test_rich_run_includes_preflight_warnings(client):
    resp = client.post(
        "/runs/rich",
        data={
            "workspace_name": "pf_ws",
            "project_name": "pf_project",
            "product_name": "pf_product",
            "product_code": "PF-001",
            "industry_code": "pet",
            "campaign_name": "pf_camp",
            "creative_preset": "meta_square_5s",
            "pipeline_mode": "copy_image_only",
            "variant_count": 4,
        },
        files=[("files", ("test.png", io.BytesIO(b"fake-png"), "image/png"))],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "_preflight" in body
    assert "severity" in body["_preflight"]


def test_rich_run_blocks_preflight_errors_before_creating_run(client):
    resp = client.post(
        "/runs/rich",
        data={
            "workspace_name": "pf_block_ws",
            "project_name": "pf_block_project",
            "product_name": "pf_block_product",
            "product_code": "PF-BLOCK-001",
            "industry_code": "pet",
            "campaign_name": "pf_block_camp",
            "creative_preset": "marketplace_main_image_pack",
            "pipeline_mode": "marketplace_main_image",
            "variant_count": 4,
        },
    )

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["error"] == "preflight_failed"
    assert detail["preflight"]["severity"] == "error"
    assert any(
        row["key"] == "marketplace_main_image.reference_media"
        for row in detail["preflight"]["checks"]
    )

    runs = client.get("/runs").json()
    assert all(run["product_code"] != "PF-BLOCK-001" for run in runs)


def test_tiktok_shop_preflight_reports_reference_ratio_and_duration_warnings(client):
    resp = client.post(
        "/runs/preflight",
        json={
            "pipeline_mode": "tiktok_shop_video",
            "has_image_inputs": False,
            "has_video_inputs": False,
            "creative_specs": {
                "video_size": "1:1",
                "video_duration_seconds": 30,
                "tiktok_video_style": "ugc_demo",
            },
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    keys = {row["key"]: row for row in payload["checks"]}
    assert keys["tiktok_shop_video.reference_media"]["severity"] == "warn"
    assert keys["tiktok_shop_video.video_size"]["severity"] == "warn"
    assert keys["tiktok_shop_video.duration"]["severity"] == "warn"


def test_preflight_warns_when_storyboard_candidate_selection_support_is_unknown(client):
    patch_resp = client.patch(
        "/agent-configs/storyboard_agent",
        json={
            "image_provider_name": "openai",
            "image_model_name": "mystery-image-model",
            "image_api_base_url": "https://example.com/v1/chat/completions",
        },
    )
    assert patch_resp.status_code == 200

    resp = client.post(
        "/runs/preflight",
        json={
            "pipeline_mode": "tiktok_shop_video",
            "has_image_inputs": True,
            "has_video_inputs": False,
            "creative_specs": {
                "video_size": "9:16",
                "video_duration_seconds": 12,
                "tiktok_video_style": "ugc_demo",
                "storyboard_candidate_count": 3,
            },
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    keys = {row["key"]: row for row in payload["checks"]}
    assert keys["storyboard_image_generation.candidate_selection"]["severity"] == "warn"


def test_preflight_reports_storyboard_image_generation_incompatibility_for_default_runs(client):
    patch_resp = client.patch(
        "/agent-configs/storyboard_agent",
        json={
            "image_provider_name": "deepseek",
            "image_model_name": "deepseek-v3.2",
            "image_api_base_url": "https://api.deepseek.com/v1/chat/completions",
        },
    )
    assert patch_resp.status_code == 200

    resp = client.post(
        "/runs/preflight",
        json={
            "pipeline_mode": "video_only",
            "has_image_inputs": False,
            "has_video_inputs": False,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    keys = {row["key"]: row for row in payload["checks"]}
    assert keys["storyboard_image_generation.image_generation"]["severity"] == "error"

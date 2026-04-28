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

from __future__ import annotations

from app.data.session import SessionLocal
from app.services.runs import execute_next_queued_stage


def _run_worker_once() -> None:
    with SessionLocal() as db:
        execute_next_queued_stage(db)
        db.commit()


def test_agent_api_default_and_override(client):
    cfg_resp = client.get("/agent-configs")
    assert cfg_resp.status_code == 200
    configs = cfg_resp.json()
    assert any(row["agent_name"] == "default" for row in configs)
    visual_qa = next(row for row in configs if row["agent_name"] == "visual_qa_agent")
    assert visual_qa["provider_name"] == "deepseek"
    assert visual_qa["model_name"] == "deepseek-v3.2"
    assert visual_qa["api_key_env"] == "CRISPY_API_KEY_DEEPSEEK"

    patch_resp = client.patch(
        "/agent-configs/gm_orchestrator",
        json={
            "provider_name": "kimi",
            "model_name": "kimi-k2.6",
            "api_base_url": "https://api.moonshot.cn/v1",
            "api_key_env": "CRISPY_API_KEY_KIMI",
            "thinking_mode": "disabled",
            "thinking_budget_tokens": 800,
            "max_output_tokens": 1200,
            "request_timeout_seconds": 30,
            "streaming_enabled": True,
        },
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["model_name"] == "kimi-k2.6"
    assert patch_resp.json()["thinking_mode"] == "disabled"
    assert patch_resp.json()["thinking_budget_tokens"] == 800
    assert patch_resp.json()["max_output_tokens"] == 1200
    assert patch_resp.json()["request_timeout_seconds"] == 30
    assert patch_resp.json()["streaming_enabled"] is True

    create_resp = client.post(
        "/runs",
        json={
            "workspace_name": "w1",
            "project_name": "p-agentcfg",
            "product_name": "pet toy",
            "product_code": "PT-001",
            "industry_code": "pet_toys",
            "campaign_name": "meta-agentcfg-1",
            "creative_preset": "meta_square_5s",
            "model_provider": "openai",
            "model_name": "gpt-4.1",
        },
    )
    run = create_resp.json()
    run_id = run["id"]

    _run_worker_once()
    run_view = client.get(f"/runs/{run_id}").json()
    intake_task = [t for t in run_view["stage_tasks"] if t["stage_name"] == "intake"][0]
    assert intake_task["metadata_json"]["resolved_api"]["source"] == "agent_override"
    assert intake_task["metadata_json"]["resolved_api"]["model_name"] == "kimi-k2.6"
    assert intake_task["metadata_json"]["resolved_api"]["thinking_mode"] == "disabled"
    assert intake_task["metadata_json"]["resolved_api"]["thinking_applied"] is False
    assert intake_task["metadata_json"]["resolved_api"]["streaming_enabled"] is True


def test_agent_api_generation_image_config(client):
    patch_resp = client.patch(
        "/agent-configs/copy_image_agent",
        json={
            "provider_name": "kimi",
            "model_name": "kimi-k2.5",
            "api_base_url": "https://api.moonshot.cn/v1",
            "api_key_env": "CRISPY_API_KEY_KIMI",
            "image_provider_name": "openai",
            "image_model_name": "gpt-image-2",
            "image_api_base_url": "https://api.apimart.ai/v1/images/generations",
            "image_api_key_env": "CRISPY_API_KEY_IMAGE",
            "video_provider_name": "openai",
            "video_model_name": "doubao-seedance-2.0",
            "video_api_base_url": "https://api.video-provider.ai/v1/videos/generations",
            "video_api_key_env": "CRISPY_API_KEY_VIDEO",
        },
    )
    assert patch_resp.status_code == 200
    row = patch_resp.json()
    assert row["image_model_name"] == "gpt-image-2"
    assert row["image_api_key_env"] == "CRISPY_API_KEY_IMAGE"
    assert row["video_model_name"] == "doubao-seedance-2.0"
    assert row["video_api_key_env"] == "CRISPY_API_KEY_VIDEO"

    all_rows = client.get("/agent-configs").json()
    gen_rows = [item for item in all_rows if item["agent_name"] == "copy_image_agent"]
    assert len(gen_rows) == 1
    gen = gen_rows[0]
    assert gen["provider_name"] == "kimi"
    assert gen["model_name"] == "kimi-k2.5"
    assert gen["image_provider_name"] == "openai"
    assert gen["image_api_base_url"] == "https://api.apimart.ai/v1/images/generations"
    assert gen["video_provider_name"] == "openai"
    assert gen["video_api_base_url"] == "https://api.video-provider.ai/v1/videos/generations"


def test_storyboard_agent_text_and_image_configs_are_separate(client):
    client.patch(
        "/agent-configs/storyboard_agent",
        json={
            "provider_name": "deepseek",
            "model_name": "deepseek-v4-pro",
            "api_base_url": "https://api.deepseek.com",
            "api_key_env": "CRISPY_API_KEY_DEEPSEEK",
        },
    )
    client.patch(
        "/agent-configs/copy_image_agent",
        json={
            "image_provider_name": "openai",
            "image_model_name": "gpt-image-2",
            "image_api_base_url": "https://api.apimart.ai/v1/images/generations",
            "image_api_key_env": "CRISPY_API_KEY_IMAGE",
        },
    )

    from app.data.session import SessionLocal
    from app.services.agent_api_configs import (
        has_resolved_image_config,
        resolve_agent_config,
        with_fallback_image_config,
    )

    with SessionLocal() as db:
        storyboard = resolve_agent_config(
            db,
            agent_name="storyboard_agent",
            run_provider="openai",
            run_model="gpt-4.1",
        )
        copy_image = resolve_agent_config(
            db,
            agent_name="copy_image_agent",
            run_provider="openai",
            run_model="gpt-4.1",
        )

    assert storyboard["provider_name"] == "deepseek"
    assert storyboard["image_api_base_url"] is None
    assert has_resolved_image_config(storyboard) is False

    storyboard_with_image = with_fallback_image_config(
        storyboard,
        copy_image,
        source="copy_image_agent",
    )
    assert storyboard_with_image["image_model_name"] == "gpt-image-2"
    assert storyboard_with_image["image_api_base_url"] == "https://api.apimart.ai/v1/images/generations"


def test_agent_api_patch_can_clear_values_and_runtime_falls_back(client):
    default_resp = client.patch(
        "/agent-configs/default",
        json={
            "provider_name": "deepseek",
            "model_name": "deepseek-v3.2",
            "api_base_url": "https://api.deepseek.com/v1",
            "api_key_env": "CRISPY_API_KEY_DEEPSEEK",
        },
    )
    assert default_resp.status_code == 200

    seeded_resp = client.patch(
        "/agent-configs/copy_image_agent",
        json={
            "provider_name": "kimi",
            "model_name": "kimi-k2.6",
            "api_base_url": "https://api.moonshot.cn/v1",
            "api_key_env": "CRISPY_API_KEY_KIMI",
            "image_provider_name": "openai",
            "image_model_name": "gpt-image-2",
            "image_api_base_url": "https://api.apimart.ai/v1/images/generations",
            "image_api_key_env": "CRISPY_API_KEY_IMAGE",
        },
    )
    assert seeded_resp.status_code == 200

    cleared_resp = client.patch(
        "/agent-configs/copy_image_agent",
        json={
            "provider_name": None,
            "model_name": None,
            "api_base_url": None,
            "api_key_env": None,
            "image_provider_name": None,
            "image_model_name": None,
            "image_api_base_url": None,
            "image_api_key_env": None,
            "max_output_tokens": None,
        },
    )
    assert cleared_resp.status_code == 200
    cleared = cleared_resp.json()
    assert cleared["provider_name"] == ""
    assert cleared["model_name"] == ""
    assert cleared["api_base_url"] is None
    assert cleared["api_key_env"] is None
    assert cleared["image_provider_name"] is None
    assert cleared["image_model_name"] is None
    assert cleared["image_api_base_url"] is None
    assert cleared["image_api_key_env"] is None

    create_resp = client.post(
        "/runs",
        json={
            "workspace_name": "w-clear",
            "project_name": "p-agentcfg-clear",
            "product_name": "pet toy",
            "product_code": "PT-CLEAR",
            "industry_code": "pet_toys",
            "campaign_name": "meta-agentcfg-clear",
            "creative_preset": "meta_square_5s",
            "model_provider": "openai",
            "model_name": "gpt-4.1",
        },
    )
    run_id = create_resp.json()["id"]

    _run_worker_once()
    run_view = client.get(f"/runs/{run_id}").json()
    intake_task = [t for t in run_view["stage_tasks"] if t["stage_name"] == "intake"][0]
    resolved_api = intake_task["metadata_json"]["resolved_api"]
    assert resolved_api["provider_name"] == "deepseek"
    assert resolved_api["model_name"] == "deepseek-v3.2"


def test_agent_api_page_loads(client, monkeypatch):
    monkeypatch.setenv("CRISPY_API_KEY_KIMI", "dummy")
    resp = client.get("/dashboard/agent-apis")
    assert resp.status_code == 200
    assert "API &amp; Integration Configs" in resp.text
    assert "default" in resp.text
    assert "CRISPY_API_KEY_KIMI" in resp.text
    assert "Copy Image Agent - Text" in resp.text
    assert "Copy Image Agent - Image" in resp.text
    assert "Storyboard Agent - Text" in resp.text
    assert "Storyboard Agent - Image" in resp.text
    assert "Video Generation Agent - Video" in resp.text
    assert "Visual QA Agent" in resp.text


def test_agent_api_env_vars_endpoint(client, monkeypatch):
    monkeypatch.setenv("CRISPY_API_KEY_OPENAI", "dummy-openai")
    monkeypatch.setenv("CRISPY_API_KEY_GEMINI", "dummy-gemini")
    monkeypatch.setenv("OTHER_PREFIX_KEY", "should-not-appear")
    resp = client.get("/agent-configs/env-vars")
    assert resp.status_code == 200
    names = resp.json()
    assert "CRISPY_API_KEY_OPENAI" in names
    assert "CRISPY_API_KEY_GEMINI" in names
    assert "OTHER_PREFIX_KEY" not in names


def test_agent_api_env_prefix_validation(client):
    resp = client.patch(
        "/agent-configs/copy_image_agent",
        json={"api_key_env": "OPENAI_API_KEY"},
    )
    assert resp.status_code == 400
    assert "CRISPY_API_KEY_" in resp.text

    image_resp = client.patch(
        "/agent-configs/copy_image_agent",
        json={"image_api_key_env": "OPENAI_API_KEY"},
    )
    assert image_resp.status_code == 400
    assert "CRISPY_API_KEY_" in image_resp.text

    video_resp = client.patch(
        "/agent-configs/copy_image_agent",
        json={"video_api_key_env": "OPENAI_API_KEY"},
    )
    assert video_resp.status_code == 400
    assert "CRISPY_API_KEY_" in video_resp.text


def test_data_dashboard_page_loads(client):
    resp = client.get("/dashboard/data")
    assert resp.status_code == 200
    assert "Data Dashboard" in resp.text
    assert "Creative Decision Attribution" in resp.text
    assert "CSV Fallback Imports" in resp.text
    assert "csv-stager" in resp.text
    assert "No CSV files staged" in resp.text
    assert "Use Shopify CSV with product_code/sku" in resp.text
    assert "chooseOfflineCsv" in resp.text
    assert "Use when APIs are unavailable" not in resp.text
    assert "csv-file-row" in resp.text
    assert "Credentials" not in resp.text
    assert "Chart.js" in resp.text or "chart.js" in resp.text.lower()
    assert "if(!window.Chart) return;" in resp.text


def test_configs_page_shows_integration_health(client):
    resp = client.get("/dashboard/agent-apis")
    assert resp.status_code == 200
    assert "Integration Health" in resp.text
    assert "Shopify" in resp.text
    assert "Meta" in resp.text
    assert "Notion" in resp.text
    assert "/content-schedules/notion-status" in resp.text


def test_data_dashboard_summary_endpoint(client):
    resp = client.get("/data-dashboard/summary?workspace_name=nonexistent&project_name=nonexistent")
    assert resp.status_code == 404
    assert "not found" in resp.text.lower()


def test_auto_sync_config_endpoint(client):
    resp = client.get("/data-dashboard/auto-sync-config?workspace_name=nonexistent")
    assert resp.status_code == 404


def test_integration_sync_uses_registry(client):
    from app.integrations.sync_service import supported_integration_platforms, sync_integration

    assert set(supported_integration_platforms()) >= {"shopify", "meta"}

    import pytest

    with pytest.raises(ValueError, match="Unsupported integration platform"):
        import asyncio
        from app.data.session import SessionLocal

        with SessionLocal() as db:
            asyncio.run(
                sync_integration(
                    "unknown",
                    db,
                    workspace_name="w",
                    project_name="p",
                )
            )

    resp = client.post(
        "/integrations/unknown/sync",
        params={"workspace_name": "w", "project_name": "p"},
    )
    assert resp.status_code == 400
    assert "shopify" in resp.text and "meta" in resp.text

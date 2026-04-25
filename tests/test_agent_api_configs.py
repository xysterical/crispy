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

    patch_resp = client.patch(
        "/agent-configs/gm_orchestrator",
        json={"provider_name": "openai", "model_name": "gpt-4.1-mini"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["model_name"] == "gpt-4.1-mini"

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
    assert intake_task["metadata_json"]["resolved_api"]["model_name"] == "gpt-4.1-mini"


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


def test_agent_api_page_loads(client, monkeypatch):
    monkeypatch.setenv("CRISPY_API_KEY_KIMI", "dummy")
    resp = client.get("/dashboard/agent-apis")
    assert resp.status_code == 200
    assert "Agent API Configs" in resp.text
    assert "default" in resp.text
    assert "CRISPY_API_KEY_KIMI" in resp.text
    assert "Copy Image Agent - Text" in resp.text
    assert "Copy Image Agent - Image" in resp.text
    assert "Video Generation Agent - Video" in resp.text


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

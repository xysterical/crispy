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
            "campaign_name": "meta-agentcfg-1",
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


def test_agent_api_page_loads(client, monkeypatch):
    monkeypatch.setenv("CRISPY_API_KEY_KIMI", "dummy")
    resp = client.get("/dashboard/agent-apis")
    assert resp.status_code == 200
    assert "Agent API Configs" in resp.text
    assert "default" in resp.text
    assert "CRISPY_API_KEY_KIMI" in resp.text


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
        "/agent-configs/generation_agent",
        json={"api_key_env": "OPENAI_API_KEY"},
    )
    assert resp.status_code == 400
    assert "CRISPY_API_KEY_" in resp.text

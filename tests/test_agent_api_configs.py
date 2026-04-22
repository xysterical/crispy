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
        "/agent-configs/research_agent",
        json={"provider_name": "kimi", "model_name": "kimi-research-v1"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["model_name"] == "kimi-research-v1"

    create_resp = client.post(
        "/runs",
        json={
            "workspace_name": "w1",
            "project_name": "p-agentcfg",
            "product_name": "pet toy",
            "campaign_name": "meta-agentcfg-1",
            "model_provider": "kimi",
            "model_name": "kimi-default-text",
        },
    )
    run = create_resp.json()
    run_id = run["id"]

    _run_worker_once()
    run_view = client.get(f"/runs/{run_id}").json()
    research_task = [t for t in run_view["stage_tasks"] if t["stage_name"] == "research"][0]
    assert research_task["metadata_json"]["resolved_api"]["source"] == "agent_override"
    assert research_task["metadata_json"]["resolved_api"]["model_name"] == "kimi-research-v1"


def test_agent_api_page_loads(client):
    resp = client.get("/dashboard/agent-apis")
    assert resp.status_code == 200
    assert "Agent API Configs" in resp.text
    assert "default" in resp.text


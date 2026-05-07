from __future__ import annotations

from app.agents.runtime import AgentsRuntime
from app.data.session import SessionLocal
from app.services.runs import execute_next_queued_stage


def _run_worker_once() -> None:
    with SessionLocal() as db:
        execute_next_queued_stage(db)
        db.commit()


def test_planning_prompt_includes_persona_contract_and_collaborators(client, monkeypatch):
    captured_prompts: list[str] = []

    def capture_chat(self, provider, model, prompt, runtime_config, **kwargs):
        captured_prompts.append(prompt)
        return "stub summary", model, 0.0

    monkeypatch.setattr(AgentsRuntime, "_chat_complete", capture_chat)

    create_resp = client.post(
        "/runs",
        json={
            "workspace_name": "persona-ws",
            "project_name": "persona-project",
            "product_name": "pet wipes",
            "product_code": "PC-001",
            "industry_code": "pet_care",
            "campaign_name": "persona-campaign",
            "creative_preset": "meta_square_5s",
        },
    )
    assert create_resp.status_code == 200
    run_id = create_resp.json()["id"]

    _run_worker_once()
    advance_resp = client.post(f"/runs/{run_id}/advance", json={"notes": "approved"})
    assert advance_resp.status_code == 200
    _run_worker_once()

    run = client.get(f"/runs/{run_id}").json()
    planning_task = next(task for task in run["stage_tasks"] if task["stage_name"] == "planning")

    assert planning_task["metadata_json"]["compiled_persona"]["lead_agent"]["agent_name"] == "planning_agent"
    assert planning_task["metadata_json"]["compiled_persona"]["lead_agent"]["section_names"]
    assert "sha256" in planning_task["metadata_json"]["compiled_persona"]

    planning_prompt = captured_prompts[-1]
    assert "Persona Contract" in planning_prompt
    assert "Planning Agent" in planning_prompt
    assert "Collaborator Context" in planning_prompt
    assert "Product Research Agent" in planning_prompt
    assert "GM Orchestrator" in planning_prompt

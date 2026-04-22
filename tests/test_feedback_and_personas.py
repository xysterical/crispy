from __future__ import annotations

from app.data.session import SessionLocal
from app.services.runs import execute_next_queued_stage


def _run_worker_once() -> None:
    with SessionLocal() as db:
        execute_next_queued_stage(db)
        db.commit()


def test_feedback_import_updates_leaderboard(client):
    create_resp = client.post(
        "/runs",
        json={
            "workspace_name": "w1",
            "project_name": "p-feedback",
            "product_name": "pet brush",
            "campaign_name": "meta-c1",
        },
    )
    run = create_resp.json()
    project_id = run["project_id"]
    run_id = run["id"]

    # Produce at least one generated artifact path for realistic key usage.
    _run_worker_once()
    client.post(f"/runs/{run_id}/advance", json={"notes": "ok"})
    _run_worker_once()
    client.post(f"/runs/{run_id}/advance", json={"notes": "ok"})
    _run_worker_once()

    import_resp = client.post(
        "/feedback/import",
        json={
            "workspace_name": "w1",
            "project_name": "p-feedback",
            "file_name": "weekly.csv",
            "rows": [
                {
                    "project_name": "p-feedback",
                    "creative_key": "V1",
                    "run_id": run_id,
                    "impressions": 1000,
                    "clicks": 35,
                    "spend": 40,
                    "conversions": 6,
                    "revenue": 130,
                },
                {
                    "project_name": "p-feedback",
                    "creative_key": "V2",
                    "run_id": run_id,
                    "impressions": 1200,
                    "clicks": 18,
                    "spend": 45,
                    "conversions": 2,
                    "revenue": 60,
                },
            ],
        },
    )
    assert import_resp.status_code == 200
    payload = import_resp.json()
    assert payload["rows"] == 2
    assert payload["snapshots_created"] == 2

    leaderboard = client.get(f"/projects/{project_id}/leaderboard")
    assert leaderboard.status_code == 200
    ranking = leaderboard.json()["ranking"]
    assert ranking[0]["weighted_score"] >= ranking[-1]["weighted_score"]
    assert ranking[0]["creative_key"] == "V1"


def test_persona_read_and_patch(client):
    catalog_resp = client.get("/personas")
    assert catalog_resp.status_code == 200
    catalog = catalog_resp.json()
    gm_row = [row for row in catalog if row["agent_name"] == "gm_orchestrator"][0]
    assert "/gm/" in gm_row["source_path"] or "personas/gm/" in gm_row["source_path"]
    research_row = [row for row in catalog if row["agent_name"] == "research_agent"][0]
    assert "stages/01_research_agent.md" in research_row["source_path"]

    get_resp = client.get("/personas/research_agent")
    assert get_resp.status_code == 200
    before = get_resp.json()
    assert "Research Agent" in before["content"]
    assert before["display_name"] == "Research Agent"
    assert before["stage"] == "research"

    patch_resp = client.patch(
        "/personas/research_agent",
        json={"content": "# Research Agent\n- Updated from dashboard.", "changed_by": "test-suite"},
    )
    assert patch_resp.status_code == 200
    after = patch_resp.json()
    assert after["version"] >= before["version"]
    assert "Updated from dashboard" in after["content"]

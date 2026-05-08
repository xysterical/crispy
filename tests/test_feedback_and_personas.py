from __future__ import annotations

from sqlalchemy import select

from app.data.models import GmInstructionVersion, GmMemory
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
            "product_code": "FB-001",
            "industry_code": "pet_care",
            "campaign_name": "meta-c1",
            "creative_preset": "meta_square_5s",
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
                    "variant_id": "V1",
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
                    "variant_id": "V2",
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
    assert payload["memory_entry_id"] is not None

    with SessionLocal() as db:
        gm_instruction = db.scalar(
            select(GmInstructionVersion).order_by(GmInstructionVersion.version.desc()).limit(1)
        )
        assert gm_instruction is not None
        assert gm_instruction.version >= 1
        product_memories = db.scalars(
            select(GmMemory).where(GmMemory.memory_scope == "product", GmMemory.product_code == "FB-001")
        ).all()
        industry_memories = db.scalars(
            select(GmMemory).where(GmMemory.memory_scope == "industry", GmMemory.industry_code == "pet_care")
        ).all()
        assert len(product_memories) >= 1
        assert len(industry_memories) >= 1
        assert "top_variants" in (product_memories[0].content or {})

    leaderboard = client.get(f"/projects/{project_id}/leaderboard")
    assert leaderboard.status_code == 200
    ranking = leaderboard.json()["ranking"]
    assert ranking[0]["weighted_score"] >= ranking[-1]["weighted_score"]
    assert ranking[0]["creative_key"] == "V1"

    gm_view = client.get("/gm-memory", params={"scope": "product", "product_code": "FB-001"})
    assert gm_view.status_code == 200
    gm_rows = gm_view.json()
    assert len(gm_rows) >= 1
    assert all(item["memory_scope"] == "product" for item in gm_rows)


def test_persona_read_and_patch(client):
    catalog_resp = client.get("/personas")
    assert catalog_resp.status_code == 200
    catalog = catalog_resp.json()
    gm_row = [row for row in catalog if row["agent_name"] == "gm_orchestrator"][0]
    assert "/gm/" in gm_row["source_path"] or "personas/gm/" in gm_row["source_path"]
    research_row = [row for row in catalog if row["agent_name"] == "product_research_agent"][0]
    assert "stages/01_product_research_agent.md" in research_row["source_path"]

    get_resp = client.get("/personas/product_research_agent")
    assert get_resp.status_code == 200
    before = get_resp.json()
    assert "Product Research Agent" in before["content"]
    assert before["display_name"] == "Product Research Agent"
    assert before["stage"] == "research"

    original_content = before["content"]
    test_content = "# Product Research Agent\n- Updated from dashboard."
    try:
        patch_resp = client.patch(
            "/personas/product_research_agent",
            json={"content": test_content, "changed_by": "test-suite"},
        )
        assert patch_resp.status_code == 200
        after = patch_resp.json()
        assert after["version"] >= before["version"]
        assert "Updated from dashboard" in after["content"]
    finally:
        client.patch(
            "/personas/product_research_agent",
            json={"content": original_content, "changed_by": "test-suite-restore"},
        )


def test_persona_dashboard_page_loads(client):
    resp = client.get("/dashboard/personas")
    assert resp.status_code == 200
    assert "Persona Board" in resp.text
    assert "Back to Dashboard" in resp.text

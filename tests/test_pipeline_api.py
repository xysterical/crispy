from __future__ import annotations

from app.data.session import SessionLocal
from app.services.runs import execute_next_queued_stage


def _run_worker_once() -> None:
    with SessionLocal() as db:
        execute_next_queued_stage(db)
        db.commit()


def test_pipeline_run_can_progress_with_human_gates(client):
    create_resp = client.post(
        "/runs",
        json={
            "workspace_name": "w1",
            "project_name": "p1",
            "product_name": "pet wipes",
            "campaign_name": "meta-us-1",
            "context": {"positioning": "premium convenience"},
        },
    )
    assert create_resp.status_code == 200
    run = create_resp.json()
    run_id = run["id"]

    # research
    _run_worker_once()
    run = client.get(f"/runs/{run_id}").json()
    assert run["current_stage"] == "research"
    assert run["status"] == "waiting_review"

    # move to ideation
    adv = client.post(f"/runs/{run_id}/advance", json={"notes": "approved"})
    assert adv.status_code == 200
    _run_worker_once()
    run = client.get(f"/runs/{run_id}").json()
    assert run["current_stage"] == "ideation"
    assert run["status"] == "waiting_review"

    # reject ideation and rerun
    rej = client.post(f"/runs/{run_id}/reject", json={"notes": "needs sharper hooks"})
    assert rej.status_code == 200
    _run_worker_once()
    run = client.get(f"/runs/{run_id}").json()
    ideation_task = [t for t in run["stage_tasks"] if t["stage_name"] == "ideation"][0]
    assert ideation_task["attempt"] >= 2
    assert run["status"] == "waiting_review"

    # generation
    client.post(f"/runs/{run_id}/advance", json={"notes": "ok"})
    _run_worker_once()
    run = client.get(f"/runs/{run_id}").json()
    assert run["current_stage"] == "generation"
    assert run["status"] == "waiting_review"

    # scoring
    client.post(f"/runs/{run_id}/advance", json={"notes": "ok"})
    _run_worker_once()
    run = client.get(f"/runs/{run_id}").json()
    assert run["current_stage"] == "scoring"
    assert run["latest_scorecard"] is not None
    assert run["latest_forecast"] is not None

    # complete
    done = client.post(f"/runs/{run_id}/advance", json={"notes": "final approve"})
    assert done.status_code == 200
    run = done.json()
    assert run["status"] == "completed"
    assert run["current_stage"] is None


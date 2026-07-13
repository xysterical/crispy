from __future__ import annotations

import io

from sqlalchemy import select

from app.data.models import GmPolicyVersion, GmReflection, StageTask
from app.data.session import SessionLocal
from app.services.runs import execute_next_queued_stage


def _run_worker_once() -> None:
    with SessionLocal() as db:
        execute_next_queued_stage(db)
        db.commit()


def _advance_run(client, run_id: str) -> None:
    resp = client.post(f"/runs/{run_id}/advance", json={"notes": "approved from test"})
    assert resp.status_code == 200


def _patch_valid_generated_images(monkeypatch) -> None:
    def fake_materialize_generated_image(_selected):
        from PIL import Image

        image = Image.new("RGB", (200, 200))
        for x in range(200):
            for y in range(200):
                image.putpixel((x, y), ((x * 3) % 255, (y * 5) % 255, ((x + y) * 2) % 255))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue(), "b64_json"

    monkeypatch.setattr("app.services.runs.runtime._materialize_generated_image", fake_materialize_generated_image)


def _create_run(client, *, product_code: str = "GM-001", pipeline_mode: str = "copy_image_only", variant_count: int = 2) -> dict:
    resp = client.post(
        "/runs",
        json={
            "workspace_name": "gm-ws",
            "project_name": "gm-project",
            "product_name": "smart pet leash",
            "product_code": product_code,
            "industry_code": "pet_care",
            "campaign_name": f"campaign-{product_code}",
            "creative_preset": "meta_square_5s",
            "pipeline_mode": pipeline_mode,
            "variant_count": variant_count,
        },
    )
    assert resp.status_code == 200
    return resp.json()


def test_feedback_import_creates_candidate_policy_and_planning_reads_active_policy(client):
    first_run = _create_run(client, product_code="GM-FB-1")

    _run_worker_once()
    _advance_run(client, first_run["id"])
    _run_worker_once()
    _advance_run(client, first_run["id"])
    _run_worker_once()

    import_resp = client.post(
        "/feedback/import",
        json={
            "workspace_name": "gm-ws",
            "project_name": "gm-project",
            "file_name": "gm_weekly.csv",
            "rows": [
                {
                    "project_name": "gm-project",
                    "creative_key": "V1",
                    "variant_id": "V1",
                    "run_id": first_run["id"],
                    "impressions": 1500,
                    "clicks": 52,
                    "spend": 50,
                    "conversions": 8,
                    "revenue": 180,
                },
                {
                    "project_name": "gm-project",
                    "creative_key": "V2",
                    "variant_id": "V2",
                    "run_id": first_run["id"],
                    "impressions": 1500,
                    "clicks": 20,
                    "spend": 50,
                    "conversions": 2,
                    "revenue": 55,
                },
            ],
        },
    )
    assert import_resp.status_code == 200

    reflections = client.get(
        "/gm-reflections",
        params={"reflection_type": "feedback_import", "scope": "product", "product_code": "GM-FB-1"},
    )
    assert reflections.status_code == 200
    reflection_rows = reflections.json()
    assert len(reflection_rows) >= 1
    assert reflection_rows[0]["payload"]["top_variants"]

    policies = client.get(
        "/gm-policies",
        params={"status": "candidate", "scope": "product", "product_code": "GM-FB-1"},
    )
    assert policies.status_code == 200
    policy_rows = policies.json()
    assert len(policy_rows) >= 1
    policy_id = policy_rows[0]["id"]
    assert policy_rows[0]["replay_status"] == "passed"
    assert policy_rows[0]["replay_score"] is not None

    promote_resp = client.post(
        f"/gm-policies/{policy_id}/promote",
        json={"changed_by": "test-suite", "notes": "activate candidate for planning"},
    )
    assert promote_resp.status_code == 200
    assert promote_resp.json()["status"] == "active"

    industry_policies = client.get(
        "/gm-policies",
        params={"scope": "industry", "industry_code": "pet_care"},
    )
    assert industry_policies.status_code == 200
    assert industry_policies.json()
    assert all(item["shop_id"] is None for item in industry_policies.json())

    second_run = _create_run(client, product_code="GM-FB-1")
    _run_worker_once()
    _advance_run(client, second_run["id"])
    _run_worker_once()

    with SessionLocal() as db:
        planning_task = db.scalar(
            select(StageTask).where(StageTask.run_id == second_run["id"], StageTask.stage_name == "planning")
        )
        assert planning_task is not None
        gm_policy = planning_task.input_payload.get("gm_policy") or {}
        assert policy_id in gm_policy.get("policy_version_ids", [])
        assert gm_policy.get("stage_guidance", {}).get("angle_priorities")


def test_candidate_policy_evaluate_endpoint_returns_gate_results(client):
    run = _create_run(client, product_code="GM-EVAL-GATE", variant_count=2)
    _run_worker_once()
    _advance_run(client, run["id"])
    _run_worker_once()
    _advance_run(client, run["id"])
    _run_worker_once()

    import_resp = client.post(
        "/feedback/import",
        json={
            "workspace_name": "gm-ws",
            "project_name": "gm-project",
            "file_name": "gm_gate.csv",
            "rows": [
                {
                    "project_name": "gm-project",
                    "creative_key": "V1",
                    "variant_id": "V1",
                    "run_id": run["id"],
                    "impressions": 1800,
                    "clicks": 60,
                    "spend": 40,
                    "conversions": 10,
                    "revenue": 220,
                },
                {
                    "project_name": "gm-project",
                    "creative_key": "V2",
                    "variant_id": "V2",
                    "run_id": run["id"],
                    "impressions": 1700,
                    "clicks": 12,
                    "spend": 40,
                    "conversions": 1,
                    "revenue": 35,
                },
            ],
        },
    )
    assert import_resp.status_code == 200
    policies = client.get(
        "/gm-policies",
        params={"scope": "product", "product_code": "GM-EVAL-GATE"},
    )
    policy_id = policies.json()[0]["id"]

    evaluate_resp = client.post(f"/gm-policies/{policy_id}/evaluate")
    assert evaluate_resp.status_code == 200
    payload = evaluate_resp.json()
    assert payload["replay_status"] == "passed"
    assert payload["replay_score"] >= 0.6
    assert payload["replay_summary"]


def test_evaluation_selection_creates_run_outcome_reflection_and_candidate_policy(client, monkeypatch):
    _patch_valid_generated_images(monkeypatch)
    run = _create_run(client, product_code="GM-EVAL-1", variant_count=2)
    for _ in range(5):
        _run_worker_once()
        _advance_run(client, run["id"])
    _run_worker_once()

    with SessionLocal() as db:
        reflection = db.scalar(
            select(GmReflection).where(
                GmReflection.run_id == run["id"],
                GmReflection.reflection_type == "run_outcome",
            )
        )
        assert reflection is not None
        assert reflection.payload.get("winner_variant_id")
        assert reflection.payload.get("variant_snapshot")

        policy = db.scalar(
            select(GmPolicyVersion).where(
                GmPolicyVersion.project_id == run["project_id"],
                GmPolicyVersion.product_code == "GM-EVAL-1",
            )
        )
        assert policy is not None
        assert policy.status == "candidate"
        assert policy.content.get("angle_priorities") or policy.content.get("evidence_digest")
        assert policy.replay_status in {"passed", "needs_review"}


def test_variant_review_creates_operator_reflection(client):
    run = _create_run(client, product_code="GM-REVIEW-1")
    _run_worker_once()
    _advance_run(client, run["id"])
    _run_worker_once()
    _advance_run(client, run["id"])
    _run_worker_once()

    review_resp = client.post(
        f"/runs/{run['id']}/variants/V1/review",
        json={
            "action": "request_regeneration",
            "comment": "background and product logic are weak",
            "tags": ["marketplace_background_not_white", "visual_qa_failed"],
        },
    )
    assert review_resp.status_code == 200

    with SessionLocal() as db:
        reflection = db.scalar(
            select(GmReflection)
            .where(
                GmReflection.run_id == run["id"],
                GmReflection.reflection_type == "operator_review",
            )
            .order_by(GmReflection.created_at.desc())
        )
        assert reflection is not None
        assert "marketplace_background_not_white" in (reflection.payload.get("hard_constraints") or [])
        assert reflection.payload.get("action") == "request_regeneration"


def test_promotion_is_blocked_when_replay_gate_not_passed(client):
    run = _create_run(client, product_code="GM-BLOCK-1")
    _run_worker_once()
    _advance_run(client, run["id"])
    _run_worker_once()
    _advance_run(client, run["id"])
    _run_worker_once()

    review_resp = client.post(
        f"/runs/{run['id']}/variants/V1/review",
        json={
            "action": "request_regeneration",
            "comment": "single weak review should not auto-promote",
            "tags": ["visual_qa_failed"],
        },
    )
    assert review_resp.status_code == 200

    policies = client.get("/gm-policies", params={"scope": "product", "product_code": "GM-BLOCK-1"})
    assert policies.status_code == 200
    policy_id = policies.json()[0]["id"]
    assert policies.json()[0]["replay_status"] in {"failed", "needs_review"}

    promote_resp = client.post(
        f"/gm-policies/{policy_id}/promote",
        json={"changed_by": "test-suite"},
    )
    assert promote_resp.status_code == 409

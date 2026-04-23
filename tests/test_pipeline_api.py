from __future__ import annotations

from pathlib import Path

from app.data.session import SessionLocal
from app.orchestrator.state_machine import STAGE_ORDER, stage_plan_for
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
            "product_code": "PW-001",
            "industry_code": "pet_care",
            "campaign_name": "meta-us-1",
            "creative_preset": "meta_square_5s",
            "context": {"positioning": "premium convenience"},
            "business_context": {
                "target_audience": "busy pet owners",
                "key_value_props": ["save time", "reduce odor"],
                "primary_cta": "Shop Now",
                "campaign_objective": "conversions",
            },
            "category_tags": ["pet_care"],
        },
    )
    assert create_resp.status_code == 200
    run = create_resp.json()
    run_id = run["id"]
    assert run["model_provider"] == "openai"
    assert run["model_name"] == "gpt-4.1"
    assert run["pipeline_mode"] == "full_multimodal"
    assert run["enable_research"] is False

    for stage in STAGE_ORDER:
        _run_worker_once()
        run = client.get(f"/runs/{run_id}").json()
        assert run["current_stage"] == stage
        assert run["status"] == "waiting_review"

        if stage == "divergence":
            rej = client.post(f"/runs/{run_id}/reject", json={"notes": "need stronger variant split"})
            assert rej.status_code == 200
            _run_worker_once()
            run = client.get(f"/runs/{run_id}").json()
            divergence_task = [t for t in run["stage_tasks"] if t["stage_name"] == "divergence"][0]
            assert divergence_task["attempt"] >= 2
            assert run["status"] == "waiting_review"

        if stage != STAGE_ORDER[-1]:
            adv = client.post(f"/runs/{run_id}/advance", json={"notes": "approved"})
            assert adv.status_code == 200

    run = client.get(f"/runs/{run_id}").json()
    assert run["latest_scorecard"] is not None
    assert run["latest_forecast"] is not None

    done = client.post(f"/runs/{run_id}/advance", json={"notes": "final approve"})
    assert done.status_code == 200
    run = done.json()
    assert run["status"] == "completed"
    assert run["current_stage"] is None


def test_run_deliverables_and_variants_endpoints(client):
    create_resp = client.post(
        "/runs",
        json={
            "workspace_name": "w2",
            "project_name": "p2",
            "product_name": "pet brush",
            "product_code": "PB-001",
            "industry_code": "pet_care",
            "campaign_name": "meta-us-2",
            "creative_preset": "meta_square_5s",
            "business_context": {"target_audience": "cat owners", "primary_cta": "Shop Now", "campaign_objective": "conversions"},
        },
    )
    run_id = create_resp.json()["id"]
    for stage in STAGE_ORDER:
        _run_worker_once()
        if stage != STAGE_ORDER[-1]:
            client.post(f"/runs/{run_id}/advance", json={"notes": "ok"})

    variants = client.get(f"/runs/{run_id}/variants")
    assert variants.status_code == 200
    variants_payload = variants.json()
    assert len(variants_payload["variants"]) > 0
    assert len(variants_payload["ranked"]) > 0

    deliverables = client.get(f"/runs/{run_id}/deliverables")
    assert deliverables.status_code == 200
    deliverables_payload = deliverables.json()
    assert deliverables_payload["winner_variant_id"] is not None
    assert "copy_variant" in deliverables_payload["deliverables"]


def test_pipeline_mode_copy_image_only(client):
    create_resp = client.post(
        "/runs",
        json={
            "workspace_name": "w3",
            "project_name": "p3",
            "product_name": "dog leash",
            "product_code": "DL-001",
            "industry_code": "pet_accessories",
            "campaign_name": "meta-copy-image-1",
            "pipeline_mode": "copy_image_only",
            "creative_preset": "meta_square_5s",
            "business_context": {"target_audience": "dog owners", "key_value_props": ["anti-pull"], "primary_cta": "Shop Now"},
        },
    )
    assert create_resp.status_code == 200
    run = create_resp.json()
    run_id = run["id"]
    plan = stage_plan_for("copy_image_only")
    assert run["pipeline_mode"] == "copy_image_only"
    assert [task["stage_name"] for task in run["stage_tasks"]] == plan

    for stage in plan:
        _run_worker_once()
        current = client.get(f"/runs/{run_id}").json()
        assert current["current_stage"] == stage
        assert current["status"] == "waiting_review"
        if stage != plan[-1]:
            client.post(f"/runs/{run_id}/advance", json={"notes": "ok"})

    final_review = client.post(f"/runs/{run_id}/advance", json={"notes": "final"})
    assert final_review.status_code == 200
    done = final_review.json()
    assert done["status"] == "completed"
    assert done["current_stage"] is None

    deliverables = client.get(f"/runs/{run_id}/deliverables")
    assert deliverables.status_code == 200
    payload = deliverables.json()["deliverables"]
    assert payload["copy_variant"] is not None
    assert payload["video_asset"] is None
    image_uri = payload["image_assets"][0]["uri"]
    image_path = Path(image_uri)
    assert image_path.exists()
    assert image_path.stat().st_size > 0


def test_pipeline_modes_endpoint(client):
    resp = client.get("/pipeline-modes")
    assert resp.status_code == 200
    modes = {item["mode"]: item for item in resp.json()}
    assert "copy_image_only" in modes
    assert "video_only" in modes
    assert "full_multimodal" in modes
    assert modes["copy_image_only"]["agent_count"] >= 1


def test_create_run_requires_product_and_industry_and_preset(client):
    resp = client.post(
        "/runs",
        json={
            "workspace_name": "w-required",
            "project_name": "p-required",
            "product_name": "missing fields",
            "campaign_name": "meta-required",
        },
    )
    assert resp.status_code == 422


def test_product_code_conflict_returns_409(client):
    first = client.post(
        "/runs",
        json={
            "workspace_name": "w-code",
            "project_name": "p-code",
            "product_name": "dog leash",
            "product_code": "DL-CODE-001",
            "industry_code": "pet_accessories",
            "campaign_name": "meta-code-1",
            "creative_preset": "meta_square_5s",
        },
    )
    assert first.status_code == 200

    second = client.post(
        "/runs",
        json={
            "workspace_name": "w-code",
            "project_name": "p-code",
            "product_name": "cat leash different name",
            "product_code": "DL-CODE-001",
            "industry_code": "pet_accessories",
            "campaign_name": "meta-code-2",
            "creative_preset": "meta_square_5s",
        },
    )
    assert second.status_code == 409
    assert "product_code conflict" in second.text


def test_creative_preset_is_materialized_into_run(client):
    resp = client.post(
        "/runs",
        json={
            "workspace_name": "w-preset",
            "project_name": "p-preset",
            "product_name": "dog leash",
            "product_code": "DL-PRESET-001",
            "industry_code": "pet_accessories",
            "campaign_name": "meta-preset-1",
            "creative_preset": "meta_vertical_5s",
            "pipeline_mode": "copy_image_only",
        },
    )
    assert resp.status_code == 200
    run = resp.json()
    assert run["creative_preset"] == "meta_vertical_5s"
    assert run["creative_specs"]["image_size"] == "9:16"
    assert run["creative_specs"]["video_duration_seconds"] == 5

    for stage in stage_plan_for("copy_image_only"):
        _run_worker_once()
        current = client.get(f"/runs/{run['id']}").json()
        if stage == "copy_image_generation":
            copy_task = [t for t in current["stage_tasks"] if t["stage_name"] == "copy_image_generation"][0]
            assets = copy_task["output_payload"]["image_assets"]
            assert len(assets) > 0
            assert assets[0]["aspect_ratio"] == "9:16"
            break
        client.post(f"/runs/{run['id']}/advance", json={"notes": "ok"})

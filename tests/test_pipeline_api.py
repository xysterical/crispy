from __future__ import annotations

from pathlib import Path

from app.data.models import VariantAsset
from app.data.session import SessionLocal
from app.providers.llm import GeneratedVideo, VideoGenResult
from app.orchestrator.state_machine import STAGE_ORDER, stage_plan_for
from app.services.runs import _build_task_input, execute_next_queued_stage


def _run_worker_once() -> None:
    with SessionLocal() as db:
        execute_next_queued_stage(db)
        db.commit()


def test_channel_is_included_in_agent_task_input(client):
    create_resp = client.post(
        "/runs",
        json={
            "workspace_name": "channel_w",
            "project_name": "channel_p",
            "product_name": "pet wipes",
            "product_code": "CH-001",
            "industry_code": "pet_care",
            "campaign_name": "tiktok-launch",
            "channel": "tiktok",
            "creative_preset": "meta_square_5s",
        },
    )
    assert create_resp.status_code == 200
    run_id = create_resp.json()["id"]

    with SessionLocal() as db:
        from app.data.models import PipelineRun, StageTask

        run = db.get(PipelineRun, run_id)
        task = db.query(StageTask).filter_by(run_id=run_id, stage_name="planning").one()
        assert _build_task_input(db, run, task)["channel"] == "tiktok"


def test_run_status_explanation_guides_operator_next_steps(client):
    create_resp = client.post(
        "/runs",
        json={
            "workspace_name": "status_w",
            "project_name": "status_p",
            "product_name": "pet wipes",
            "product_code": "STATUS-001",
            "industry_code": "pet_care",
            "campaign_name": "status-campaign",
            "creative_preset": "meta_square_5s",
            "pipeline_mode": "copy_image_only",
        },
    )
    assert create_resp.status_code == 200
    created = create_resp.json()
    run_id = created["id"]

    assert created["status_explanation"]["tone"] == "info"
    assert created["status_explanation"]["headline"] == "Queued for intake"
    assert created["status_explanation"]["primary_action"] == "Wait for worker"

    _run_worker_once()
    waiting = client.get(f"/runs/{run_id}").json()
    assert waiting["status"] == "waiting_review"
    assert waiting["status_explanation"]["tone"] == "review"
    assert waiting["status_explanation"]["headline"] == "Intake is waiting for review"
    assert waiting["status_explanation"]["primary_action"] == "Review and approve"
    assert "Approve to continue" in waiting["status_explanation"]["next_actions"]

    with SessionLocal() as db:
        from app.data.models import PipelineRun, RunStatus, StageTask, TaskStatus

        run = db.get(PipelineRun, run_id)
        task = db.query(StageTask).filter_by(run_id=run_id, stage_name="intake").one()
        run.status = RunStatus.FAILED.value
        task.status = TaskStatus.FAILED.value
        task.error_message = "provider timeout"
        db.commit()

    failed = client.get(f"/runs/{run_id}").json()
    assert failed["status_explanation"]["tone"] == "danger"
    assert failed["status_explanation"]["headline"] == "Intake failed"
    assert failed["status_explanation"]["detail"] == "provider timeout"
    assert failed["status_explanation"]["primary_action"] == "Reject to retry"


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
    assert run["variant_summary"]["total"] == 0

    for stage in STAGE_ORDER:
        _run_worker_once()
        run = client.get(f"/runs/{run_id}").json()
        assert run["current_stage"] == stage
        assert run["status"] == "waiting_review"
        current_task = [t for t in run["stage_tasks"] if t["stage_name"] == stage][0]
        assert current_task["metadata_json"]["stage_contract_version"] == "commercial-pilot-v2"
        assert current_task["metadata_json"]["persona_snapshots"]
        stage_events = [event for event in run["trace_events"] if event["stage_name"] == stage]
        assert any(event["event_type"] == "started" for event in stage_events)
        assert any(event["event_type"] == "input_summary" for event in stage_events)
        assert any(event["event_type"] == "handoff" for event in stage_events)
        assert any(event["event_type"] == "completed" for event in stage_events)
        if stage in {"copy_image_generation", "storyboard_image_generation", "video_generation"}:
            provider_events = [event for event in stage_events if event["event_type"] == "provider_selection"]
            assert provider_events
            assert all(event["payload"]["decision_type"] == "generation_provider_selection" for event in provider_events)
            assert all(event["provider_name"] == event["payload"]["selected_provider_name"] for event in provider_events)

        if stage == "divergence":
            assert run["variant_summary"]["total"] == run["variant_count"]
            rej = client.post(f"/runs/{run_id}/reject", json={"notes": "need stronger variant split"})
            assert rej.status_code == 200
            _run_worker_once()
            run = client.get(f"/runs/{run_id}").json()
            divergence_task = [t for t in run["stage_tasks"] if t["stage_name"] == "divergence"][0]
            assert divergence_task["attempt"] >= 2
            assert run["status"] == "waiting_review"
            assert any(event["event_type"] == "human_rejected" for event in run["trace_events"])

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
    assert any(event["event_type"] == "human_approved" for event in run["trace_events"])
    events_resp = client.get(f"/runs/{run_id}/events", params={"once": True})
    assert events_resp.status_code == 200
    assert "event: agent_trace" in events_resp.text
    assert "data:" in events_resp.text


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
    assert len(variants_payload["items"]) == 8
    assert variants_payload["summary"]["winner_count"] == 1
    assert variants_payload["summary"]["filtered_count"] == 8
    assert variants_payload["summary"]["quality_flag_counts"]["winner"] == 1
    assert variants_payload["items"][0]["assets"]
    assert variants_payload["items"][0]["scores"]
    assert variants_payload["items"][0]["quality_summary"]["required_asset_types"]
    image_asset = next(asset for item in variants_payload["items"] for asset in item["assets"] if asset["asset_type"] == "image")
    assert "visual_qa" in image_asset["payload"]
    assert image_asset["payload"]["visual_qa"]["status"] in {"pass", "warn", "fail"}

    winner_variants = client.get(f"/runs/{run_id}/variants", params={"quality": "winner"})
    assert winner_variants.status_code == 200
    winner_payload = winner_variants.json()
    assert winner_payload["summary"]["filtered_count"] == 1
    assert len(winner_payload["items"]) == 1
    assert winner_payload["items"][0]["is_winner"] is True

    high_score_variants = client.get(f"/runs/{run_id}/variants", params={"min_score": 1})
    assert high_score_variants.status_code == 200
    assert high_score_variants.json()["items"]

    deliverables = client.get(f"/runs/{run_id}/deliverables")
    assert deliverables.status_code == 200
    deliverables_payload = deliverables.json()
    assert deliverables_payload["winner_variant_id"] is not None
    assert "copy_variant" in deliverables_payload["deliverables"]
    run_payload = client.get(f"/runs/{run_id}").json()
    planning_task = next(task for task in run_payload["stage_tasks"] if task["stage_name"] == "planning")
    divergence_task = next(task for task in run_payload["stage_tasks"] if task["stage_name"] == "divergence")
    visual_qa_task = next(task for task in run_payload["stage_tasks"] if task["stage_name"] == "visual_quality_assessment")
    evaluation_task = next(task for task in run_payload["stage_tasks"] if task["stage_name"] == "evaluation_selection")
    assert planning_task["output_payload"]["strategy_handoff"]["handoff_standard"] == "commercial-pilot-v2"
    assert divergence_task["output_payload"]["experiment_matrix"]
    assert visual_qa_task["metadata_json"]["agent_name"] == "visual_qa_agent"
    assert visual_qa_task["metadata_json"]["resolved_api"]["provider_name"] == "deepseek"
    assert visual_qa_task["output_payload"]["variant_summaries"]
    assert visual_qa_task["output_payload"]["model_media_inputs"]["image_count"] > 0
    assert any(score["score_type"] == "visual_quality" for score in variants_payload["items"][0]["scores"])
    ranked_first = evaluation_task["output_payload"]["evaluation_result"]["ranked_variants"][0]
    assert "visual_qa" in ranked_first["sub_scores"]
    assert any(reason.startswith("visual_qa_agent_status=") for reason in ranked_first["reasons"])


def test_variant_review_endpoints_update_variant_library(client):
    create_resp = client.post(
        "/runs",
        json={
            "workspace_name": "w-variant-review",
            "project_name": "p-variant-review",
            "product_name": "pet brush",
            "product_code": "VR-001",
            "industry_code": "pet_care",
            "campaign_name": "meta-us-review",
            "creative_preset": "meta_square_5s",
        },
    )
    run_id = create_resp.json()["id"]
    for stage in STAGE_ORDER:
        _run_worker_once()
        if stage != STAGE_ORDER[-1]:
            client.post(f"/runs/{run_id}/advance", json={"notes": "ok"})

    variants_payload = client.get(f"/runs/{run_id}/variants").json()
    target = variants_payload["items"][1]["variant_id"]
    before_target = next(item for item in variants_payload["items"] if item["variant_id"] == target)
    before_asset_count = len(before_target["assets"])

    shortlist = client.post(
        f"/runs/{run_id}/variants/{target}/select",
        json={"shortlist": True, "comment": "keep for review"},
    )
    assert shortlist.status_code == 200
    assert shortlist.json()["shortlisted"] is True

    regen = client.post(
        f"/runs/{run_id}/variants/{target}/regenerate",
        json={"reason": "need a different hook", "target_stage": "copy_image_generation"},
    )
    assert regen.status_code == 200
    assert regen.json()["regenerate_requested"] is False
    assert regen.json()["review_status"] == "regenerated"
    assert len(regen.json()["assets"]) > before_asset_count
    assert regen.json()["metadata_json"]["latest_regeneration"]["target_stage"] == "copy_image_generation"
    run_after_regen = client.get(f"/runs/{run_id}").json()
    assert any(event["event_type"] == "regeneration_started" for event in run_after_regen["trace_events"])
    assert any(event["event_type"] == "regeneration_completed" for event in run_after_regen["trace_events"])

    winner = client.post(
        f"/runs/{run_id}/variants/{target}/select",
        json={"winner": True, "comment": "manual winner"},
    )
    assert winner.status_code == 200
    assert winner.json()["is_winner"] is True

    review = client.post(
        f"/runs/{run_id}/variants/{target}/review",
        json={"action": "approve_variant", "comment": "approved by operator"},
    )
    assert review.status_code == 200
    assert review.json()["review_status"] == "approved"


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
    assert "dtc_site_image" in modes
    assert "video_only" in modes
    assert "full_multimodal" in modes
    assert "marketplace_main_image" in modes
    assert "tiktok_shop_video" in modes
    assert modes["copy_image_only"]["agent_count"] >= 1
    assert modes["dtc_site_image"]["display_name"] == "DTC Site Image"
    assert modes["dtc_site_image"]["stages"] == modes["copy_image_only"]["stages"]
    assert modes["marketplace_main_image"]["display_name"] == "Studio Main Image"
    assert modes["marketplace_main_image"]["stages"] == modes["copy_image_only"]["stages"]
    assert modes["tiktok_shop_video"]["display_name"] == "TikTok Shop Video"
    assert modes["tiktok_shop_video"]["stages"] == stage_plan_for("video_only")


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


def test_pipeline_mode_tiktok_shop_video_materializes_defaults(client):
    create_resp = client.post(
        "/runs",
        json={
            "workspace_name": "w-tiktok",
            "project_name": "p-tiktok",
            "product_name": "pet grooming glove",
            "product_code": "TT-001",
            "industry_code": "pet_care",
            "campaign_name": "tiktok-shop-video",
            "pipeline_mode": "tiktok_shop_video",
            "creative_preset": "custom",
            "creative_specs": {
                "image_size": "9:16",
                "video_size": "9:16",
                "resolution": "720p",
                "video_duration_seconds": 12,
                "tiktok_video_style": "direct_response_ad",
            },
            "enable_research": True,
        },
    )
    assert create_resp.status_code == 200
    run = create_resp.json()
    assert run["pipeline_mode"] == "tiktok_shop_video"
    assert run["creative_preset"] == "tiktok_shop_conversion_12s"
    assert run["creative_specs"]["platform"] == "tiktok"
    assert run["creative_specs"]["creative_goal"] == "shop_conversion_video"
    assert run["creative_specs"]["tiktok_video_style"] == "direct_response_ad"
    assert run["creative_specs"]["platform_targets"] == ["tiktok", "tiktok_shop"]
    assert run["enable_research"] is False
    assert [task["stage_name"] for task in run["stage_tasks"]] == stage_plan_for("tiktok_shop_video")


def test_pipeline_mode_dtc_site_image_materializes_defaults(client):
    create_resp = client.post(
        "/runs",
        json={
            "workspace_name": "w-dtc",
            "project_name": "p-dtc",
            "product_name": "pet carrier",
            "product_code": "DTC-001",
            "industry_code": "pet_accessories",
            "campaign_name": "dtc-site-image",
            "pipeline_mode": "dtc_site_image",
            "creative_preset": "custom",
            "creative_specs": {
                "image_size": "4:5",
                "resolution": "1600px",
            },
            "enable_research": True,
        },
    )
    assert create_resp.status_code == 200
    run = create_resp.json()
    assert run["pipeline_mode"] == "dtc_site_image"
    assert run["creative_preset"] == "dtc_site_image_pack"
    assert run["creative_specs"]["asset_goal"] == "dtc_site_image"
    assert run["creative_specs"]["image_size"] == "4:5"
    assert run["creative_specs"]["resolution"] == "1600px"
    assert run["creative_specs"]["site_surface"] == "pdp_primary"
    assert run["creative_specs"]["platform_targets"] == ["shopify"]
    assert run["enable_research"] is True
    assert [task["stage_name"] for task in run["stage_tasks"]] == stage_plan_for("dtc_site_image")


def test_pipeline_mode_dtc_site_image_accepts_site_surface_override(client):
    create_resp = client.post(
        "/runs",
        json={
            "workspace_name": "w-dtc-hero",
            "project_name": "p-dtc-hero",
            "product_name": "pet carrier",
            "product_code": "DTC-002",
            "industry_code": "pet_accessories",
            "campaign_name": "dtc-site-hero",
            "pipeline_mode": "dtc_site_image",
            "creative_preset": "custom",
            "creative_specs": {
                "image_size": "4:5",
                "resolution": "1600px",
                "site_surface": "homepage_hero",
            },
        },
    )
    assert create_resp.status_code == 200
    run = create_resp.json()
    assert run["creative_specs"]["site_surface"] == "homepage_hero"


def test_dtc_site_surface_changes_planning_and_image_prompt(client):
    def create_run_for_surface(surface: str, code: str) -> dict:
        resp = client.post(
            "/runs",
            json={
                "workspace_name": f"w-dtc-surface-{surface}",
                "project_name": f"p-dtc-surface-{surface}",
                "product_name": f"pet carrier {surface}",
                "product_code": code,
                "industry_code": "pet_accessories",
                "campaign_name": f"dtc-{surface}",
                "pipeline_mode": "dtc_site_image",
                "creative_preset": "custom",
                "variant_count": 1,
                "creative_specs": {
                    "image_size": "4:5",
                    "resolution": "1600px",
                    "site_surface": surface,
                },
                "business_context": {
                    "target_audience": "urban dog owners",
                    "key_value_props": ["airline-friendly form", "comfortable ventilation"],
                    "primary_cta": "Shop Now",
                },
            },
        )
        assert resp.status_code == 200
        run_id = resp.json()["id"]
        for stage in ["intake", "planning", "divergence", "copy_image_generation"]:
            _run_worker_once()
            run_payload = client.get(f"/runs/{run_id}").json()
            if stage != "copy_image_generation":
                approve = client.post(f"/runs/{run_id}/advance", json={"notes": "ok"})
                assert approve.status_code == 200
        return client.get(f"/runs/{run_id}").json()

    hero_run = create_run_for_surface("homepage_hero", "DTC-SURFACE-HERO")
    pdp_run = create_run_for_surface("pdp_primary", "DTC-SURFACE-PDP")

    hero_planning = next(task for task in hero_run["stage_tasks"] if task["stage_name"] == "planning")["output_payload"]
    pdp_planning = next(task for task in pdp_run["stage_tasks"] if task["stage_name"] == "planning")["output_payload"]
    hero_image = next(task for task in hero_run["stage_tasks"] if task["stage_name"] == "copy_image_generation")["output_payload"]["image_assets"][0]
    pdp_image = next(task for task in pdp_run["stage_tasks"] if task["stage_name"] == "copy_image_generation")["output_payload"]["image_assets"][0]

    assert hero_planning["surface_strategy"]["site_surface"] == "homepage_hero"
    assert hero_planning["surface_strategy"]["composition_focus"] == "brand_story_scene"
    assert "homepage hero" in hero_image["prompt"].lower()
    assert "headline-safe negative space" in hero_image["prompt"].lower()
    assert "social media ad image" not in hero_image["prompt"].lower()

    assert pdp_planning["surface_strategy"]["site_surface"] == "pdp_primary"
    assert pdp_planning["surface_strategy"]["composition_focus"] == "product_dominant_detail"
    assert "pdp primary" in pdp_image["prompt"].lower()
    assert "product should dominate the frame" in pdp_image["prompt"].lower()
    assert "social media ad image" not in pdp_image["prompt"].lower()


def test_dtc_site_surface_adds_surface_specific_review_hints(client):
    def create_run_to_visual_qa(surface: str, code: str) -> tuple[dict, dict]:
        resp = client.post(
            "/runs",
            json={
                "workspace_name": f"w-dtc-review-{surface}",
                "project_name": f"p-dtc-review-{surface}",
                "product_name": f"pet carrier review {surface}",
                "product_code": code,
                "industry_code": "pet_accessories",
                "campaign_name": f"dtc-review-{surface}",
                "pipeline_mode": "dtc_site_image",
                "creative_preset": "custom",
                "variant_count": 1,
                "creative_specs": {
                    "image_size": "4:5",
                    "resolution": "1600px",
                    "site_surface": surface,
                },
            },
        )
        assert resp.status_code == 200
        run_id = resp.json()["id"]
        for stage in ["intake", "planning", "divergence", "copy_image_generation", "visual_quality_assessment"]:
            _run_worker_once()
            if stage != "visual_quality_assessment":
                approve = client.post(f"/runs/{run_id}/advance", json={"notes": "ok"})
                assert approve.status_code == 200
        run_payload = client.get(f"/runs/{run_id}").json()
        variants_payload = client.get(f"/runs/{run_id}/variants").json()
        return run_payload, variants_payload

    hero_run, hero_variants = create_run_to_visual_qa("homepage_hero", "DTC-REVIEW-HERO")
    pdp_run, pdp_variants = create_run_to_visual_qa("pdp_primary", "DTC-REVIEW-PDP")

    hero_summary = next(task for task in hero_run["stage_tasks"] if task["stage_name"] == "visual_quality_assessment")["output_payload"]["variant_summaries"][0]
    pdp_summary = next(task for task in pdp_run["stage_tasks"] if task["stage_name"] == "visual_quality_assessment")["output_payload"]["variant_summaries"][0]
    hero_quality = hero_variants["items"][0]["quality_summary"]
    pdp_quality = pdp_variants["items"][0]["quality_summary"]

    assert any("headline-safe space" in hint.lower() for hint in hero_summary["review_hints"])
    assert any("brand atmosphere" in hint.lower() for hint in hero_summary["review_hints"])
    assert any("headline-safe space" in hint.lower() for hint in hero_quality["review_hints"])

    assert any("product occupies enough of the frame" in hint.lower() for hint in pdp_summary["review_hints"])
    assert any("material or structure details" in hint.lower() for hint in pdp_summary["review_hints"])
    assert any("product occupies enough of the frame" in hint.lower() for hint in pdp_quality["review_hints"])


def test_dtc_site_image_rejects_unknown_site_surface(client):
    create_resp = client.post(
        "/runs",
        json={
            "workspace_name": "w-dtc-invalid-surface",
            "project_name": "p-dtc-invalid-surface",
            "product_name": "pet carrier invalid surface",
            "product_code": "DTC-INVALID-SURFACE",
            "industry_code": "pet_accessories",
            "campaign_name": "dtc-invalid-surface",
            "pipeline_mode": "dtc_site_image",
            "creative_preset": "custom",
            "creative_specs": {
                "image_size": "4:5",
                "resolution": "1600px",
                "site_surface": "story_card",
            },
        },
    )
    assert create_resp.status_code == 400
    assert "creative_specs.site_surface" in create_resp.text


def test_runs_preflight_reports_video_generation_incompatibility(client):
    patch_resp = client.patch(
        "/agent-configs/video_generation_agent",
        json={
            "video_provider_name": "deepseek",
            "video_model_name": "deepseek-v3.2",
            "video_api_base_url": "https://api.deepseek.com/v1/chat/completions",
        },
    )
    assert patch_resp.status_code == 200

    resp = client.post(
        "/runs/preflight",
        json={
            "pipeline_mode": "video_only",
            "has_image_inputs": False,
            "has_video_inputs": False,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is False
    assert payload["severity"] == "error"
    keys = [row["key"] for row in payload["checks"]]
    assert "video_generation.video_generation" in keys


def test_tiktok_shop_preflight_rejects_invalid_style(client):
    resp = client.post(
        "/runs/preflight",
        json={
            "pipeline_mode": "tiktok_shop_video",
            "has_image_inputs": True,
            "has_video_inputs": False,
            "creative_specs": {
                "video_size": "9:16",
                "video_duration_seconds": 12,
                "tiktok_video_style": "viral_dance",
            },
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is False
    assert payload["severity"] == "error"
    assert "tiktok_shop_video.style" in [row["key"] for row in payload["checks"]]


def test_tiktok_shop_video_scripting_outputs_tiktok_payload(client):
    create_resp = client.post(
        "/runs",
        json={
            "workspace_name": "w-tiktok-script",
            "project_name": "p-tiktok-script",
            "product_name": "travel toiletry bag",
            "product_code": "TT-SCRIPT-001",
            "industry_code": "travel",
            "campaign_name": "tiktok-script",
            "pipeline_mode": "tiktok_shop_video",
            "creative_preset": "tiktok_shop_conversion_12s",
            "creative_specs": {"tiktok_video_style": "ugc_demo"},
            "business_context": {
                "target_audience": "frequent travelers",
                "key_value_props": ["keeps bottles upright", "clear compartments"],
                "primary_cta": "Shop on TikTok",
            },
            "manual_research_brief": "Show a creator packing for a weekend trip.",
        },
    )
    assert create_resp.status_code == 200
    run_id = create_resp.json()["id"]

    for stage in ["intake", "planning", "divergence", "video_scripting"]:
        _run_worker_once()
        run = client.get(f"/runs/{run_id}").json()
        if stage != "video_scripting":
            client.post(f"/runs/{run_id}/advance", json={"notes": "ok"})

    script_task = next(task for task in run["stage_tasks"] if task["stage_name"] == "video_scripting")
    first_script = script_task["output_payload"]["scripts"][0]
    assert first_script["tiktok"]["style"] == "ugc_demo"
    assert first_script["tiktok"]["opening_hook"]
    assert first_script["tiktok"]["on_screen_text"]
    assert first_script["tiktok"]["voiceover_lines"]
    assert first_script["tiktok"]["shot_timing"][0]["intent"] == "thumb_stop"
    assert first_script["tiktok"]["cta"] == "Shop on TikTok"


def test_tiktok_shop_evaluation_includes_tiktok_scores(client):
    create_resp = client.post(
        "/runs",
        json={
            "workspace_name": "w-tiktok-eval",
            "project_name": "p-tiktok-eval",
            "product_name": "desk cable clips",
            "product_code": "TT-EVAL-001",
            "industry_code": "office",
            "campaign_name": "tiktok-eval",
            "pipeline_mode": "tiktok_shop_video",
            "creative_preset": "tiktok_shop_conversion_12s",
            "creative_specs": {"tiktok_video_style": "direct_response_ad"},
            "business_context": {
                "target_audience": "home office workers",
                "key_value_props": ["clean desk setup"],
                "primary_cta": "Shop Now",
            },
        },
    )
    assert create_resp.status_code == 200
    run_id = create_resp.json()["id"]
    for stage in stage_plan_for("tiktok_shop_video"):
        _run_worker_once()
        run = client.get(f"/runs/{run_id}").json()
        if stage != "evaluation_selection":
            client.post(f"/runs/{run_id}/advance", json={"notes": "ok"})

    evaluation_task = next(task for task in run["stage_tasks"] if task["stage_name"] == "evaluation_selection")
    ranked = evaluation_task["output_payload"]["evaluation_result"]["ranked_variants"][0]
    for key in [
        "thumb_stop_power",
        "product_clarity",
        "purchase_intent",
        "native_tiktok_feel",
        "watch_through_potential",
        "claim_safety",
        "generation_feasibility",
    ]:
        assert key in ranked["sub_scores"]


def test_runs_preflight_reports_intake_video_understanding_incompatibility(client):
    patch_resp = client.patch(
        "/agent-configs/gm_orchestrator",
        json={
            "provider_name": "deepseek",
            "model_name": "deepseek-v3.2",
            "api_base_url": "https://api.deepseek.com/v1",
        },
    )
    assert patch_resp.status_code == 200

    resp = client.post(
        "/runs/preflight",
        json={
            "pipeline_mode": "copy_image_only",
            "has_image_inputs": False,
            "has_video_inputs": True,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is False
    assert payload["severity"] == "error"
    keys = [row["key"] for row in payload["checks"]]
    assert "intake.video_understanding" in keys


def test_assets_refresh_recovers_external_video_task(client, monkeypatch):
    create_resp = client.post(
        "/runs",
        json={
            "workspace_name": "w-refresh",
            "project_name": "p-refresh",
            "product_name": "dog leash",
            "product_code": "DL-REFRESH-001",
            "industry_code": "pet_accessories",
            "campaign_name": "meta-refresh",
            "pipeline_mode": "video_only",
            "creative_preset": "meta_vertical_5s",
        },
    )
    run_id = create_resp.json()["id"]
    for stage in ["intake", "planning", "divergence"]:
        _run_worker_once()
        client.post(f"/runs/{run_id}/advance", json={"notes": "ok"})

    with SessionLocal() as db:
        variant = db.query(VariantAsset).filter(VariantAsset.run_id == run_id).first()
        assert variant is None
        from app.data.models import RunVariant

        run_variant = db.query(RunVariant).filter(RunVariant.run_id == run_id, RunVariant.variant_id == "V1").one()
        db.add(
            VariantAsset(
                run_variant_id=run_variant.id,
                run_id=run_id,
                stage_name="video_generation",
                asset_type="video",
                uri=f"assets/{run_id}/V1_sample.mp4",
                provider_name="stub",
                model_name="stub-video",
                prompt_summary="video asset for V1",
                idempotency_key="test-refresh-video-v1",
                payload={
                    "variant_id": "V1",
                    "video_uri": f"assets/{run_id}/V1_sample.mp4",
                    "external_task_id": "task_refresh_1",
                    "generation_status": "processing",
                    "source": "external_task_pending",
                },
            )
        )
        db.commit()

    class FakeProvider:
        def poll_video_task(self, **kwargs):
            return VideoGenResult(
                model_used="stub-video",
                task_id=kwargs["task_id"],
                status="completed",
                videos=[
                    GeneratedVideo(
                        url="https://example.com/video.mp4",
                        task_id=kwargs["task_id"],
                        status="completed",
                    )
                ],
            )

    monkeypatch.setattr("app.services.runs.runtime.providers.get", lambda _name: FakeProvider())
    monkeypatch.setattr("app.services.runs.runtime._materialize_generated_video", lambda _selected: (b"fake-video-bytes", "url"))

    resp = client.post(f"/runs/{run_id}/assets/refresh")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["refreshed"] == 1
    assert payload["completed"] == 1

    variants = client.get(f"/runs/{run_id}/variants").json()
    v1 = next(item for item in variants["items"] if item["variant_id"] == "V1")
    video = next(asset for asset in v1["assets"] if asset["asset_type"] == "video")
    assert video["payload"]["generation_status"] == "completed"
    assert Path(video["uri"]).exists()
    assert Path(video["uri"]).read_bytes() == b"fake-video-bytes"


def test_assets_refresh_updates_stage_output_and_downstream_inputs(client, monkeypatch):
    create_resp = client.post(
        "/runs",
        json={
            "workspace_name": "w-refresh-stage",
            "project_name": "p-refresh-stage",
            "product_name": "travel organizer",
            "product_code": "REFRESH-STAGE-001",
            "industry_code": "travel",
            "campaign_name": "video-refresh-stage",
            "pipeline_mode": "video_only",
            "creative_preset": "meta_vertical_5s",
        },
    )
    run_id = create_resp.json()["id"]
    for stage in ["intake", "planning", "divergence"]:
        _run_worker_once()
        client.post(f"/runs/{run_id}/advance", json={"notes": "ok"})

    with SessionLocal() as db:
        from app.data.models import PipelineRun, RunVariant, StageTask

        run = db.get(PipelineRun, run_id)
        run_variant = db.query(RunVariant).filter(RunVariant.run_id == run_id, RunVariant.variant_id == "V1").one()
        video_task = db.query(StageTask).filter_by(run_id=run_id, stage_name="video_generation").one()
        visual_task = db.query(StageTask).filter_by(run_id=run_id, stage_name="visual_quality_assessment").one()
        stale_payload = {
            "variant_id": "V1",
            "video_uri": f"assets/{run_id}/V1_sample.mp4",
            "external_task_id": "task_refresh_stage_1",
            "generation_status": "processing",
            "source": "external_task_pending",
        }
        video_task.output_payload = {"videos": [dict(stale_payload)]}
        db.add(
            VariantAsset(
                run_variant_id=run_variant.id,
                run_id=run_id,
                stage_name="video_generation",
                asset_type="video",
                uri=stale_payload["video_uri"],
                provider_name="stub",
                model_name="stub-video",
                prompt_summary="video asset for V1",
                idempotency_key="test-refresh-stage-output-v1",
                payload=dict(stale_payload),
            )
        )
        visual_task.input_payload = _build_task_input(db, run, visual_task)
        db.commit()

    class FakeProvider:
        def poll_video_task(self, **kwargs):
            return VideoGenResult(
                model_used="stub-video",
                task_id=kwargs["task_id"],
                status="completed",
                videos=[
                    GeneratedVideo(
                        url="https://example.com/video.mp4",
                        task_id=kwargs["task_id"],
                        status="completed",
                    )
                ],
            )

    monkeypatch.setattr("app.services.runs.runtime.providers.get", lambda _name: FakeProvider())
    monkeypatch.setattr("app.services.runs.runtime._materialize_generated_video", lambda _selected: (b"fake-video-bytes", "url"))
    monkeypatch.setattr(
        "app.services.runs.runtime._sample_generated_video_frames",
        lambda **kwargs: (
            [f"assets/{run_id}/V1_generated_video_frame_1.png", f"assets/{run_id}/V1_generated_video_frame_2.png", f"assets/{run_id}/V1_generated_video_frame_3.png"],
            [
                {"frame_id": "f1", "variant_id": "V1", "uri": f"assets/{run_id}/V1_generated_video_frame_1.png", "frame_index": 1},
                {"frame_id": "f2", "variant_id": "V1", "uri": f"assets/{run_id}/V1_generated_video_frame_2.png", "frame_index": 2},
                {"frame_id": "f3", "variant_id": "V1", "uri": f"assets/{run_id}/V1_generated_video_frame_3.png", "frame_index": 3},
            ],
        ),
    )

    resp = client.post(f"/runs/{run_id}/assets/refresh")
    assert resp.status_code == 200

    with SessionLocal() as db:
        from app.data.models import PipelineRun, StageTask

        run = db.get(PipelineRun, run_id)
        video_task = db.query(StageTask).filter_by(run_id=run_id, stage_name="video_generation").one()
        refreshed_video = video_task.output_payload["videos"][0]
        assert refreshed_video["generation_status"] == "completed"
        assert refreshed_video["video_uri"].endswith("V1_sample.mp4")
        assert refreshed_video["frame_uris"] == [
            f"assets/{run_id}/V1_generated_video_frame_1.png",
            f"assets/{run_id}/V1_generated_video_frame_2.png",
            f"assets/{run_id}/V1_generated_video_frame_3.png",
        ]

        visual_task = db.query(StageTask).filter_by(run_id=run_id, stage_name="visual_quality_assessment").one()
        rebuilt_input = _build_task_input(db, run, visual_task)
        rebuilt_video = rebuilt_input["videos"]["videos"][0]
        assert rebuilt_video["generation_status"] == "completed"
        assert rebuilt_video["video_uri"] == refreshed_video["video_uri"]
        assert rebuilt_video["frame_uris"] == refreshed_video["frame_uris"]


def test_assets_refresh_requeues_full_auto_visual_qa_after_materialization(client, monkeypatch):
    create_resp = client.post(
        "/runs",
        json={
            "workspace_name": "w-refresh-resume",
            "project_name": "p-refresh-resume",
            "product_name": "travel organizer",
            "product_code": "REFRESH-RESUME-001",
            "industry_code": "travel",
            "campaign_name": "video-refresh-resume",
            "pipeline_mode": "video_only",
            "approval_mode": "full_auto",
            "creative_preset": "meta_vertical_5s",
        },
    )
    run_id = create_resp.json()["id"]
    for stage in ["intake", "planning", "divergence"]:
        _run_worker_once()
        client.post(f"/runs/{run_id}/advance", json={"notes": "ok"})

    with SessionLocal() as db:
        from app.data.models import PipelineRun, RunStatus, RunVariant, StageTask, TaskStatus

        run = db.get(PipelineRun, run_id)
        run.status = RunStatus.WAITING_REVIEW.value
        run.current_stage = "visual_quality_assessment"
        run_variant = db.query(RunVariant).filter(RunVariant.run_id == run_id, RunVariant.variant_id == "V1").one()
        video_task = db.query(StageTask).filter_by(run_id=run_id, stage_name="video_generation").one()
        visual_task = db.query(StageTask).filter_by(run_id=run_id, stage_name="visual_quality_assessment").one()
        stale_payload = {
            "variant_id": "V1",
            "video_uri": f"assets/{run_id}/V1_sample.mp4",
            "external_task_id": "task_refresh_resume_1",
            "generation_status": "processing",
            "source": "external_task_pending",
        }
        video_task.output_payload = {"videos": [dict(stale_payload)]}
        db.add(
            VariantAsset(
                run_variant_id=run_variant.id,
                run_id=run_id,
                stage_name="video_generation",
                asset_type="video",
                uri=stale_payload["video_uri"],
                provider_name="stub",
                model_name="stub-video",
                prompt_summary="video asset for V1",
                idempotency_key="test-refresh-resume-v1",
                payload=dict(stale_payload),
            )
        )
        visual_task.status = TaskStatus.WAITING_REVIEW.value
        visual_task.output_payload = {
            "variant_summaries": [
                {"variant_id": "V1", "recommended_action": "wait_for_asset", "qa_status": "pending"}
            ]
        }
        visual_task.input_payload = _build_task_input(db, run, visual_task)
        db.commit()

    class FakeProvider:
        def poll_video_task(self, **kwargs):
            return VideoGenResult(
                model_used="stub-video",
                task_id=kwargs["task_id"],
                status="completed",
                videos=[
                    GeneratedVideo(
                        url="https://example.com/video.mp4",
                        task_id=kwargs["task_id"],
                        status="completed",
                    )
                ],
            )

    monkeypatch.setattr("app.services.runs.runtime.providers.get", lambda _name: FakeProvider())
    monkeypatch.setattr("app.services.runs.runtime._materialize_generated_video", lambda _selected: (b"fake-video-bytes", "url"))
    monkeypatch.setattr(
        "app.services.runs.runtime._sample_generated_video_frames",
        lambda **kwargs: (
            [f"assets/{run_id}/V1_generated_video_frame_1.png"],
            [{"frame_id": "f1", "variant_id": "V1", "uri": f"assets/{run_id}/V1_generated_video_frame_1.png", "frame_index": 1}],
        ),
    )

    resp = client.post(f"/runs/{run_id}/assets/refresh")
    assert resp.status_code == 200

    with SessionLocal() as db:
        from app.data.models import PipelineRun, StageTask, TaskStatus

        run = db.get(PipelineRun, run_id)
        visual_task = db.query(StageTask).filter_by(run_id=run_id, stage_name="visual_quality_assessment").one()
        assert run.status == "running"
        assert run.current_stage == "visual_quality_assessment"
        assert visual_task.status == TaskStatus.QUEUED.value
        assert visual_task.input_payload["videos"]["videos"][0]["generation_status"] == "completed"
        assert visual_task.input_payload["videos"]["videos"][0]["frame_uris"] == [
            f"assets/{run_id}/V1_generated_video_frame_1.png"
        ]


def test_variant_quality_summary_exposes_frame_review_flags(client):
    create_resp = client.post(
        "/runs",
        json={
            "workspace_name": "frame-review-w",
            "project_name": "frame-review-p",
            "product_name": "travel organizer",
            "product_code": "FRAME-001",
            "industry_code": "travel",
            "campaign_name": "frame-review-campaign",
            "pipeline_mode": "video_only",
            "creative_preset": "meta_vertical_5s",
        },
    )
    run_id = create_resp.json()["id"]

    with SessionLocal() as db:
        from app.data.models import RunVariant, VariantScore

        run_variant = RunVariant(
            run_id=run_id,
            variant_id="V1",
            angle="product-first opening",
            hook="Show the organizer before the mess",
            message="Lead with a clear first frame and keep continuity stable.",
        )
        db.add(run_variant)
        db.flush()
        db.add(
            VariantAsset(
                run_variant_id=run_variant.id,
                run_id=run_id,
                stage_name="copy_image_generation",
                asset_type="image",
                uri=f"assets/{run_id}/V1_reference.png",
                provider_name="stub",
                model_name="stub-image",
                prompt_summary="reference-backed image asset for V1",
                idempotency_key="frame-review-v1-image",
                payload={
                    "variant_id": "V1",
                    "image_uri": f"assets/{run_id}/V1_reference.png",
                    "generation_status": "completed",
                    "reference_source_count": 2,
                    "visual_qa": {
                        "status": "pass",
                        "score": 91,
                        "flags": [],
                        "checks": [],
                    },
                },
            )
        )
        db.add(
            VariantAsset(
                run_variant_id=run_variant.id,
                run_id=run_id,
                stage_name="video_generation",
                asset_type="video",
                uri=f"assets/{run_id}/V1_sample.mp4",
                provider_name="stub",
                model_name="stub-video",
                prompt_summary="video asset for V1",
                idempotency_key="frame-review-v1-video",
                payload={
                    "variant_id": "V1",
                    "video_uri": f"assets/{run_id}/V1_sample.mp4",
                    "generation_status": "completed",
                    "visual_qa": {
                        "status": "warn",
                        "score": 84,
                        "flags": [
                            "visual_qa_needs_frame_review",
                            "visual_qa_first_frame_clarity_check",
                        ],
                        "checks": [
                            {
                                "key": "frame_sequence",
                                "status": "manual_review",
                                "message": "Review the opening frame for hook clarity.",
                            }
                        ],
                    },
                },
            )
        )
        db.add(
            VariantScore(
                run_variant_id=run_variant.id,
                run_id=run_id,
                stage_name="visual_quality_assessment",
                score_type="visual_quality",
                total_score=84,
                compliance_level="warn",
                recommended_action="manual_review",
                sub_scores={"visual_score": 84, "blocking_issue_count": 0},
                reasons=["visual_qa_needs_frame_review"],
                forecast={},
                payload={
                    "variant_id": "V1",
                    "asset_reports": [
                        {
                            "asset_type": "video",
                            "flags": [
                                "visual_qa_needs_frame_review",
                                "visual_qa_first_frame_clarity_check",
                            ],
                        }
                    ],
                },
            )
        )
        db.commit()

    variants = client.get(f"/runs/{run_id}/variants")
    assert variants.status_code == 200
    payload = variants.json()
    item = next(entry for entry in payload["items"] if entry["variant_id"] == "V1")
    assert item["quality_summary"]["frame_review_flags"] == [
        "visual_qa_first_frame_clarity_check",
        "visual_qa_needs_frame_review",
    ]
    assert item["quality_summary"]["reference_source_count"] == 2


def test_dashboard_variant_board_exposes_compact_social_quality_badges(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.text
    assert "Frame review" in html
    assert "Ref-backed" in html


def test_plain_runs_blocks_preflight_errors_before_creating_run(client):
    patch_resp = client.patch(
        "/agent-configs/video_generation_agent",
        json={
            "video_provider_name": "deepseek",
            "video_model_name": "deepseek-v3.2",
            "video_api_base_url": "https://api.deepseek.com/v1/chat/completions",
        },
    )
    assert patch_resp.status_code == 200

    resp = client.post(
        "/runs",
        json={
            "workspace_name": "plain-preflight-ws",
            "project_name": "plain-preflight-project",
            "product_name": "plain-preflight-product",
            "product_code": "PLAIN-PF-001",
            "industry_code": "pet",
            "campaign_name": "plain-preflight-campaign",
            "creative_preset": "meta_square_5s",
            "pipeline_mode": "video_only",
        },
    )

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["error"] == "preflight_failed"
    assert detail["preflight"]["severity"] == "error"
    assert any(
        row["key"] == "video_generation.video_generation"
        for row in detail["preflight"]["checks"]
    )

    runs = client.get("/runs").json()
    assert all(run["product_code"] != "PLAIN-PF-001" for run in runs)


def test_plain_runs_accept_remote_reference_media_from_creative_specs(client):
    resp = client.post(
        "/runs",
        json={
            "workspace_name": "plain-remote-media-ws",
            "project_name": "plain-remote-media-project",
            "product_name": "plain-remote-media-product",
            "product_code": "PLAIN-REMOTE-001",
            "industry_code": "pet",
            "campaign_name": "plain-remote-media-campaign",
            "creative_preset": "marketplace_main_image_pack",
            "pipeline_mode": "marketplace_main_image",
            "creative_specs": {
                "image_urls": [
                    "https://cdn.example.com/reference/front-shot.png?width=1600&v=2"
                ],
                "video_urls": [
                    "https://cdn.example.com/reference/demo.mp4?download=1"
                ],
            },
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["id"]
    assert payload["product_code"] == "PLAIN-REMOTE-001"

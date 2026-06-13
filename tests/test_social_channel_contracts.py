from app.data.session import SessionLocal
from app.services.runs import _build_task_input
from app.services.creative_specs import get_social_review_contract


def test_tiktok_shop_video_contract_prefers_first_frame_and_product_truth():
    contract = get_social_review_contract(
        channel="tiktok",
        pipeline_mode="tiktok_shop_video",
        creative_specs={"video_size": "9:16"},
    )
    assert contract["review_profile"] == "social_video"
    assert contract["preferred_video_size"] == "9:16"
    assert "first_frame_clarity" in contract["required_checks"]
    assert "product_truth" in contract["required_checks"]


def test_meta_image_contract_keeps_static_social_requirements():
    contract = get_social_review_contract(
        channel="meta",
        pipeline_mode="copy_image_only",
        creative_specs={"image_size": "1:1"},
    )
    assert contract["review_profile"] == "social_image"
    assert contract["preferred_image_size"] == "1:1"
    assert "product_visibility" in contract["required_checks"]
    assert "text_overlay_risk" in contract["required_checks"]


def test_build_task_input_includes_social_review_contract_for_tiktok_video_run(client):
    create_resp = client.post(
        "/runs",
        json={
            "workspace_name": "social-contracts",
            "project_name": "shop-video",
            "product_name": "pet wipes",
            "product_code": "SOCIAL-001",
            "industry_code": "pet_care",
            "campaign_name": "tiktok-launch",
            "channel": "tiktok",
            "pipeline_mode": "tiktok_shop_video",
            "creative_preset": "tiktok_shop_conversion_12s",
            "creative_specs": {"video_size": "9:16"},
        },
    )
    assert create_resp.status_code == 200
    run_id = create_resp.json()["id"]

    with SessionLocal() as db:
        from app.data.models import PipelineRun, StageTask

        run = db.get(PipelineRun, run_id)
        task = db.query(StageTask).filter_by(run_id=run_id, stage_name="planning").one()
        task_input = _build_task_input(db, run, task)

    contract = task_input["social_review_contract"]
    assert contract["review_profile"] == "social_video"
    assert "first_frame_clarity" in contract["required_checks"]
    assert "product_truth" in contract["required_checks"]

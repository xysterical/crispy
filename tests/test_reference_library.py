from pathlib import Path

import pytest

from app.data.models import Campaign, PipelineRun, Product, Project, RunVariant, VariantAsset, Workspace
from app.services.reference_library import build_reference_bundle


@pytest.fixture
def seeded_reference_assets(db_session, tmp_path):
    from PIL import Image

    workspace = Workspace(name="ref_ws", industry_code="pet")
    db_session.add(workspace)
    db_session.flush()

    project = Project(workspace_id=workspace.id, name="ref_project")
    db_session.add(project)
    db_session.flush()

    product = Product(project_id=project.id, name="ref_product", product_code="REF-001")
    db_session.add(product)
    db_session.flush()

    tiktok_campaign = Campaign(project_id=project.id, product_id=product.id, name="ref_campaign_tiktok", channel="tiktok")
    meta_campaign = Campaign(project_id=project.id, product_id=product.id, name="ref_campaign_meta", channel="meta")
    db_session.add_all([tiktok_campaign, meta_campaign])
    db_session.flush()

    top_run = PipelineRun(
        workspace_id=workspace.id,
        project_id=project.id,
        product_id=product.id,
        campaign_id=tiktok_campaign.id,
        product_code="REF-001",
        pipeline_mode="tiktok_shop_video",
    )
    lower_run = PipelineRun(
        workspace_id=workspace.id,
        project_id=project.id,
        product_id=product.id,
        campaign_id=tiktok_campaign.id,
        product_code="REF-001",
        pipeline_mode="tiktok_shop_video",
    )
    other_channel_run = PipelineRun(
        workspace_id=workspace.id,
        project_id=project.id,
        product_id=product.id,
        campaign_id=meta_campaign.id,
        product_code="REF-001",
        pipeline_mode="full_multimodal",
    )
    db_session.add_all([top_run, lower_run, other_channel_run])
    db_session.flush()

    top_variant = RunVariant(
        run_id=top_run.id,
        variant_id="V1",
        angle="angle",
        hook="hook",
        message="message",
        current_score=96.0,
    )
    lower_variant = RunVariant(
        run_id=lower_run.id,
        variant_id="V2",
        angle="angle lower",
        hook="hook lower",
        message="message lower",
        current_score=88.0,
    )
    failed_variant = RunVariant(
        run_id=top_run.id,
        variant_id="V4",
        angle="angle failed",
        hook="hook failed",
        message="message failed",
        current_score=98.0,
    )
    other_channel_variant = RunVariant(
        run_id=other_channel_run.id,
        variant_id="V3",
        angle="angle other",
        hook="hook other",
        message="message other",
        current_score=99.0,
    )
    db_session.add_all([top_variant, lower_variant, failed_variant, other_channel_variant])
    db_session.flush()

    top_image_path = tmp_path / "winner.png"
    lower_image_path = tmp_path / "winner_2.png"
    failed_image_path = tmp_path / "winner_failed.png"
    other_channel_image_path = tmp_path / "winner_meta.png"
    frame_path = tmp_path / "winner_frame.png"
    Image.new("RGB", (1200, 1200), color=(255, 255, 255)).save(top_image_path, format="PNG")
    Image.new("RGB", (1200, 1200), color=(245, 245, 245)).save(lower_image_path, format="PNG")
    Image.new("RGB", (1200, 1200), color=(235, 235, 235)).save(failed_image_path, format="PNG")
    Image.new("RGB", (1200, 1200), color=(230, 230, 230)).save(other_channel_image_path, format="PNG")
    Image.new("RGB", (720, 1280), color=(240, 240, 240)).save(frame_path, format="PNG")

    db_session.add_all(
        [
            VariantAsset(
                run_variant_id=top_variant.id,
                run_id=top_run.id,
                stage_name="copy_image_generation",
                asset_type="image",
                uri=str(top_image_path),
                idempotency_key="ref-image-1",
                payload={"visual_qa": {"status": "pass", "score": 95}},
            ),
            VariantAsset(
                run_variant_id=lower_variant.id,
                run_id=lower_run.id,
                stage_name="copy_image_generation",
                asset_type="image",
                uri=str(lower_image_path),
                idempotency_key="ref-image-2",
                payload={"visual_qa": {"status": "pass", "score": 92}},
            ),
            VariantAsset(
                run_variant_id=failed_variant.id,
                run_id=top_run.id,
                stage_name="copy_image_generation",
                asset_type="image",
                uri=str(failed_image_path),
                idempotency_key="ref-image-failed",
                payload={"visual_qa": {"status": "fail", "score": 10}},
            ),
            VariantAsset(
                run_variant_id=other_channel_variant.id,
                run_id=other_channel_run.id,
                stage_name="copy_image_generation",
                asset_type="image",
                uri=str(other_channel_image_path),
                idempotency_key="ref-image-meta",
                payload={"visual_qa": {"status": "pass", "score": 99}},
            ),
            VariantAsset(
                run_variant_id=top_variant.id,
                run_id=top_run.id,
                stage_name="storyboard_image_generation",
                asset_type="storyboard_frame",
                uri=str(frame_path),
                idempotency_key="ref-frame-1",
                payload={"visual_qa": {"status": "pass", "score": 91}},
            ),
        ]
    )
    db_session.commit()
    return {"run_id": top_run.id, "variant_id": top_variant.id}


def test_reference_bundle_prefers_high_score_passed_assets(db_session, seeded_reference_assets):
    bundle = build_reference_bundle(
        db_session,
        product_code="REF-001",
        channel="tiktok",
        limit_images=2,
        limit_frames=2,
    )
    assert len(bundle["images"]) == 2
    assert [item["score"] for item in bundle["images"]] == [96.0, 88.0]
    assert all("winner_failed.png" not in item["uri"] for item in bundle["images"])
    assert all(item["source_type"] == "historical_image" for item in bundle["images"])
    assert all(item["channel"] == "tiktok" for item in bundle["images"])
    assert all(item["score"] is not None for item in bundle["images"])


def test_reference_bundle_includes_storyboard_frames_when_available(db_session, seeded_reference_assets):
    bundle = build_reference_bundle(
        db_session,
        product_code="REF-001",
        channel="tiktok",
        limit_images=1,
        limit_frames=2,
    )
    assert bundle["frames"]
    assert all(item["asset_type"] == "storyboard_frame" for item in bundle["frames"])
    assert all(item["channel"] == "tiktok" for item in bundle["frames"])

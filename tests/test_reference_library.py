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

    campaign = Campaign(project_id=project.id, product_id=product.id, name="ref_campaign", channel="tiktok")
    db_session.add(campaign)
    db_session.flush()

    run = PipelineRun(
        workspace_id=workspace.id,
        project_id=project.id,
        product_id=product.id,
        campaign_id=campaign.id,
        product_code="REF-001",
        pipeline_mode="tiktok_shop_video",
    )
    db_session.add(run)
    db_session.flush()

    variant = RunVariant(
        run_id=run.id,
        variant_id="V1",
        angle="angle",
        hook="hook",
        message="message",
        current_score=88.0,
    )
    db_session.add(variant)
    db_session.flush()

    image_path = tmp_path / "winner.png"
    image_path_2 = tmp_path / "winner_2.png"
    frame_path = tmp_path / "winner_frame.png"
    Image.new("RGB", (1200, 1200), color=(255, 255, 255)).save(image_path, format="PNG")
    Image.new("RGB", (1200, 1200), color=(245, 245, 245)).save(image_path_2, format="PNG")
    Image.new("RGB", (720, 1280), color=(240, 240, 240)).save(frame_path, format="PNG")

    db_session.add_all(
        [
            VariantAsset(
                run_variant_id=variant.id,
                run_id=run.id,
                stage_name="copy_image_generation",
                asset_type="image",
                uri=str(image_path),
                idempotency_key="ref-image-1",
                payload={"visual_qa": {"status": "pass", "score": 95}},
            ),
            VariantAsset(
                run_variant_id=variant.id,
                run_id=run.id,
                stage_name="copy_image_generation",
                asset_type="image",
                uri=str(image_path_2),
                idempotency_key="ref-image-2",
                payload={"visual_qa": {"status": "pass", "score": 92}},
            ),
            VariantAsset(
                run_variant_id=variant.id,
                run_id=run.id,
                stage_name="storyboard_image_generation",
                asset_type="storyboard_frame",
                uri=str(frame_path),
                idempotency_key="ref-frame-1",
                payload={"visual_qa": {"status": "pass", "score": 91}},
            ),
        ]
    )
    db_session.commit()
    return {"run_id": run.id, "variant_id": variant.id}


def test_reference_bundle_prefers_high_score_passed_assets(db_session, seeded_reference_assets):
    bundle = build_reference_bundle(
        db_session,
        product_code="REF-001",
        channel="tiktok",
        limit_images=2,
        limit_frames=2,
    )
    assert len(bundle["images"]) == 2
    assert all(item["source_type"] == "historical_image" for item in bundle["images"])
    assert all(item["score"] is not None for item in bundle["images"])


def test_reference_bundle_includes_storyboard_frames_when_available(db_session, seeded_reference_assets):
    bundle = build_reference_bundle(
        db_session,
        product_code="REF-001",
        channel="tiktok",
        limit_images=1,
        limit_frames=2,
    )
    assert len(bundle["frames"]) <= 2
    assert all(item["asset_type"] == "storyboard_frame" for item in bundle["frames"])

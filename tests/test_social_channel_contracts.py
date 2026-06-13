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

import pytest
from app.schemas.contracts import ShotFramePlan, ShotPlanItem, VideoScriptItem


class TestShotContracts:
    def test_shot_frame_plan_defaults(self):
        frame = ShotFramePlan(description="Product close-up shot")
        assert frame.description == "Product close-up shot"
        assert frame.visible_product_elements == []

    def test_shot_plan_item_minimal(self):
        shot = ShotPlanItem(
            shot_id="shot_1",
            variant_id="V1",
            intent="product_proof",
            first_frame=ShotFramePlan(description="Product close-up"),
        )
        assert shot.shot_id == "shot_1"
        assert shot.last_frame is None
        assert shot.motion_description == ""
        assert shot.product_continuity_constraints == []

    def test_shot_plan_item_full(self):
        shot = ShotPlanItem(
            shot_id="shot_2",
            variant_id="V1",
            intent="cta_packshot",
            duration_seconds=2.0,
            first_frame=ShotFramePlan(
                description="Product packshot",
                visible_product_elements=["product", "logo"],
            ),
            last_frame=ShotFramePlan(description="CTA end card"),
            motion_description="Slow zoom out",
            audio_description="Voiceover: Shop Now",
            text_overlay="Limited Time Offer",
            product_continuity_constraints=["color_match", "scale_consistent"],
        )
        assert shot.duration_seconds == 2.0
        assert shot.last_frame.description == "CTA end card"
        assert len(shot.product_continuity_constraints) == 2

    def test_video_script_item_backward_compat(self):
        item = VideoScriptItem(
            variant_id="V1",
            hook="Test hook",
            script="Test script",
            shot_list=["shot 1", "shot 2"],
        )
        assert item.shot_plan == []
        assert len(item.shot_list) == 2

    def test_video_script_item_with_shot_plan(self):
        shot = ShotPlanItem(
            shot_id="s1",
            variant_id="V1",
            intent="thumb_stop",
            first_frame=ShotFramePlan(description="Attention grab"),
        )
        item = VideoScriptItem(
            variant_id="V1",
            hook="Hook",
            script="Script",
            shot_list=["old shot"],
            shot_plan=[shot],
        )
        assert len(item.shot_plan) == 1
        assert item.shot_plan[0].intent == "thumb_stop"
        assert len(item.shot_list) == 1

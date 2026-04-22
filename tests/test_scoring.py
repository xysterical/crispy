from __future__ import annotations

from app.scoring.engine import compliance_check, score_bundle
from app.schemas.contracts import CreativeBundle, CopyVariant, ImageAssetRef, VideoPlan


def _bundle(text: str) -> CreativeBundle:
    return CreativeBundle(
        copy_variants=[
            CopyVariant(
                variant_id="V1",
                primary_text=text,
                headline="headline",
                description="desc",
                call_to_action="Shop Now",
            )
        ],
        image_assets=[ImageAssetRef(variant_id="V1", uri="/tmp/a.png", prompt="prompt")],
        video_plan=VideoPlan(hook="hook", script=text),
        video_sample_uri="/tmp/sample.mp4",
    )


def test_high_risk_claim_is_hard_blocked():
    bundle = _bundle("This product is a guaranteed cure for all pet disease.")
    compliance = compliance_check(bundle)
    assert compliance.blocked is True
    assert compliance.level.value == "high"


def test_score_bundle_returns_forecast():
    bundle = _bundle("Clean faster with practical daily routine.")
    compliance = compliance_check(bundle)
    scorecard, forecast = score_bundle(bundle, compliance)
    assert 0 <= scorecard.total_score <= 100
    assert 0 <= forecast.score_0_100 <= 100
    assert 0 <= forecast.confidence_0_1 <= 1


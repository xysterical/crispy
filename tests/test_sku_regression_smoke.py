from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from app.agents.runtime import AgentsRuntime
from app.schemas.contracts import ProductIntake


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sku_regression"
MANIFEST_PATH = FIXTURE_DIR / "manifest.json"
VALID_PIPELINE_MODES = {
    "copy_image_only",
    "marketplace_main_image",
    "video_only",
    "full_multimodal",
    "tiktok_shop_video",
}
REQUIRED_CHECKS = {
    "no_placeholder_asset",
    "product_truth_contract",
    "image_asset_contract",
    "qa_driven_repair_prompt",
}


def test_sku_regression_manifest_is_runtime_ready():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    runtime = AgentsRuntime()
    seen_skus: set[str] = set()

    assert manifest["version"] == 1
    assert len(manifest["skus"]) >= 4

    for sku in manifest["skus"]:
        sku_id = sku["sku_id"]
        assert sku_id not in seen_skus
        seen_skus.add(sku_id)
        assert sku["pipeline_mode"] in VALID_PIPELINE_MODES
        assert REQUIRED_CHECKS.issubset(set(sku["expected_checks"]))

        reference_images = []
        for image_ref in sku["reference_images"]:
            image_path = FIXTURE_DIR / image_ref
            assert image_path.is_file(), image_ref
            with Image.open(image_path) as image:
                assert image.width >= 256
                assert image.height >= 256
            reference_images.append(str(image_path))

        truth = dict(sku["product_truth_contract"])
        truth["reference_images"] = reference_images
        assert truth["must_preserve"]
        assert truth["colors"]
        assert truth["forbidden_changes"]

        intake = ProductIntake(
            product_name=sku["product_name"],
            category_tags=[sku["category"]],
            asset_media_summary=sku["asset_media_summary"],
            image_references=[{"uri": uri, "role": "primary_reference"} for uri in reference_images],
            product_truth_contract=truth,
        )

        resolved_truth = runtime._product_truth_contract(intake)
        assert resolved_truth["product_name"] == sku["product_name"]
        assert resolved_truth["must_preserve"] == truth["must_preserve"]
        assert resolved_truth["reference_images"] == reference_images

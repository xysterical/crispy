from __future__ import annotations

import json
from pathlib import Path

from app.analytics.sku_regression_scorecard import build_sku_regression_scorecard


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sku_regression"
MANIFEST_PATH = FIXTURE_DIR / "manifest.json"


def test_sku_regression_scorecard_summarizes_batch_results(tmp_path):
    image_path = tmp_path / "cup.png"
    image_path.write_bytes(b"fake image bytes")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    results = {
        "batch": "sku-regression-demo",
        "results": [
            {
                "sku_id": "antipull_harness",
                "ok": True,
                "generation_status": "completed",
                "image_uri": str(image_path),
                "visual_qa": {"status": "warn", "flags": ["visual_qa_product_truth_structure_review"]},
                "image_provider": "apimart",
                "image_model": "gpt-image-2",
            },
            {
                "sku_id": "pull_on_dog_raincoat",
                "ok": False,
                "error": "image generation failed local QA: visual_qa_placeholder",
                "visual_qa_flags": ["visual_qa_placeholder"],
            },
            {
                "sku_id": "custom_print_paper_cup",
                "ok": True,
                "generation_status": "submitted",
                "external_task_id": "task_123",
            },
            {
                "sku_id": "brush_for_shoes",
                "ok": True,
                "generation_status": "completed",
                "image_uri": str(image_path),
                "visual_qa_status": "pass",
                "visual_proof_reviews": [{"status": "pass"}],
            },
        ],
    }

    scorecard = build_sku_regression_scorecard(manifest, results, asset_root=Path.cwd())

    assert scorecard["batch_id"] == "sku-regression-demo"
    assert scorecard["totals"] == {
        "total": 4,
        "pass": 1,
        "warn": 1,
        "fail": 1,
        "pending": 1,
        "missing": 0,
        "average_score": 52.5,
    }
    rows = {row["sku_id"]: row for row in scorecard["skus"]}
    assert rows["antipull_harness"]["status"] == "warn"
    assert rows["antipull_harness"]["asset_exists"] is True
    assert rows["antipull_harness"]["asset_size_bytes"] == len(b"fake image bytes")
    assert rows["pull_on_dog_raincoat"]["status"] == "fail"
    assert "invalid_or_placeholder_asset" in rows["pull_on_dog_raincoat"]["reasons"]
    assert rows["custom_print_paper_cup"]["status"] == "pending"
    assert rows["custom_print_paper_cup"]["external_task_id"] == "task_123"

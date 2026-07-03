from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def build_sku_regression_scorecard(
    manifest: dict[str, Any],
    run_results: dict[str, Any] | None = None,
    *,
    asset_root: Path | None = None,
) -> dict[str, Any]:
    results_by_sku = {str(item.get("sku_id")): item for item in (run_results or {}).get("results", []) if item.get("sku_id")}
    rows = [_score_sku(sku, results_by_sku.get(sku["sku_id"], {}), asset_root=asset_root) for sku in manifest.get("skus", [])]
    totals = {
        "total": len(rows),
        "pass": sum(1 for row in rows if row["status"] == "pass"),
        "warn": sum(1 for row in rows if row["status"] == "warn"),
        "fail": sum(1 for row in rows if row["status"] == "fail"),
        "pending": sum(1 for row in rows if row["status"] == "pending"),
        "missing": sum(1 for row in rows if row["status"] == "missing"),
    }
    scored = [row["score"] for row in rows if row["score"] is not None]
    totals["average_score"] = round(sum(scored) / len(scored), 1) if scored else None
    return {
        "version": 1,
        "fixture_version": manifest.get("version"),
        "batch_id": (run_results or {}).get("batch") or (run_results or {}).get("batch_id"),
        "totals": totals,
        "skus": rows,
    }


def _score_sku(sku: dict[str, Any], result: dict[str, Any], *, asset_root: Path | None) -> dict[str, Any]:
    if not result:
        return _row(sku, "missing", None, ["no_run_result"], result)

    reasons: list[str] = []
    status = str(result.get("generation_status") or result.get("status") or "").lower()
    ok = bool(result.get("ok"))
    asset_contract = result.get("asset_contract") or result.get("image_asset_contract") or {}
    visual_qa = result.get("visual_qa") or {}
    flags = list(result.get("visual_qa_flags") or visual_qa.get("flags") or asset_contract.get("flags") or [])

    if status in {"queued", "submitted", "pending", "processing"}:
        return _row(sku, "pending", 45, [f"task_{status}"], result, flags)

    if result.get("error"):
        reasons.append(str(result["error"]))
    if asset_contract.get("blocking"):
        reasons.append("image_asset_contract_blocking")
    if any("placeholder" in str(flag) or "decode_error" in str(flag) for flag in flags):
        reasons.append("invalid_or_placeholder_asset")

    image_uri = result.get("image_uri") or result.get("output_path") or result.get("image_path")
    asset_info = _asset_info(image_uri, asset_root)
    if image_uri and asset_root is not None:
        if not asset_info["exists"]:
            reasons.append("missing_asset_file")

    visual_proof_status = _visual_proof_status(result)
    if visual_proof_status == "fail":
        reasons.append("visual_proof_failed")

    if reasons:
        return _row(sku, "fail", 25 if ok else 0, reasons, result, flags, asset_info)

    qa_status = str(result.get("visual_qa_status") or visual_qa.get("status") or asset_contract.get("status") or "").lower()
    if ok and qa_status == "pass" and visual_proof_status in {"", "pass"}:
        return _row(sku, "pass", 90, [], result, flags, asset_info)
    if ok:
        warn_reasons = []
        if qa_status and qa_status != "pass":
            warn_reasons.append(f"qa_{qa_status}")
        if visual_proof_status and visual_proof_status != "pass":
            warn_reasons.append(f"visual_proof_{visual_proof_status}")
        return _row(sku, "warn", 75, warn_reasons or ["needs_manual_review"], result, flags, asset_info)
    return _row(sku, "fail", 0, ["run_not_ok"], result, flags, asset_info)


def _asset_info(image_uri: Any, asset_root: Path | None) -> dict[str, Any]:
    if not image_uri:
        return {"exists": False, "size_bytes": None}
    image_path = Path(str(image_uri))
    if not image_path.is_absolute() and asset_root is not None:
        image_path = asset_root / image_path
    if not image_path.is_file():
        return {"exists": False, "size_bytes": None}
    return {"exists": True, "size_bytes": image_path.stat().st_size}


def _visual_proof_status(result: dict[str, Any]) -> str:
    reviews = result.get("visual_proof_reviews") or (result.get("visual_qa") or {}).get("visual_proof_reviews") or []
    statuses = {str(review.get("status", "")).lower() for review in reviews if isinstance(review, dict)}
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    if "pass" in statuses:
        return "pass"
    return ""


def _row(
    sku: dict[str, Any],
    status: str,
    score: int | None,
    reasons: list[str],
    result: dict[str, Any],
    flags: list[Any] | None = None,
    asset_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    asset_info = asset_info or {"exists": False, "size_bytes": None}
    return {
        "sku_id": sku["sku_id"],
        "product_name": sku.get("product_name"),
        "category": sku.get("category"),
        "status": status,
        "score": score,
        "reasons": reasons,
        "flags": [str(flag) for flag in (flags or [])],
        "image_uri": result.get("image_uri") or result.get("output_path") or result.get("image_path"),
        "asset_exists": asset_info["exists"],
        "asset_size_bytes": asset_info["size_bytes"],
        "external_task_id": result.get("external_task_id") or result.get("task_id"),
        "provider": result.get("image_provider") or result.get("provider"),
        "model": result.get("image_model") or result.get("model"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a fixed SKU regression scorecard from fixture manifest and run results.")
    parser.add_argument("--manifest", default="tests/fixtures/sku_regression/manifest.json")
    parser.add_argument("--results")
    parser.add_argument("--out")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    results = json.loads(Path(args.results).read_text(encoding="utf-8")) if args.results else None
    scorecard = build_sku_regression_scorecard(manifest, results, asset_root=Path.cwd())
    text = json.dumps(scorecard, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()

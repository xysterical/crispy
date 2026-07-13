from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.data.models import GmMemory, PerformanceSnapshot, PipelineRun, RunVariant, VariantAsset, VariantScore


MIN_IMPRESSIONS = 1000
MIN_CLICKS = 20
MIN_SPEND = 20.0


class CreativeDecisionAnalyzer:
    def __init__(self, db: Session, project_id: str) -> None:
        self.db = db
        self.project_id = project_id

    def decision_report(
        self,
        *,
        product_code: str | None = None,
        window_days: int = 30,
        limit: int = 200,
    ) -> dict:
        since = datetime.now(UTC) - timedelta(days=window_days)
        query = (
            select(PerformanceSnapshot)
            .where(
                PerformanceSnapshot.project_id == self.project_id,
                PerformanceSnapshot.created_at >= since,
            )
            .order_by(desc(PerformanceSnapshot.created_at))
            .limit(limit)
        )
        snapshots = self.db.scalars(query).all()

        groups: dict[str, list[PerformanceSnapshot]] = defaultdict(list)
        unmatched: list[dict] = []
        for snapshot in snapshots:
            metrics = snapshot.metrics or {}
            attribution = metrics.get("attribution") if isinstance(metrics.get("attribution"), dict) else {}
            if not attribution.get("strategy_safe"):
                unmatched.append(self._unmatched_item(snapshot, attribution))
                continue
            run = self.db.get(PipelineRun, attribution.get("run_id") or snapshot.run_id)
            if product_code and (not run or run.product_code != product_code):
                continue
            groups[snapshot.creative_key].append(snapshot)

        candidates = [self._candidate_item(key, rows) for key, rows in groups.items()]
        sufficient = [
            item
            for item in candidates
            if item["evidence"]["sufficient"] and not item["quality"]["blocking"]
        ]
        baseline = self._baseline(sufficient)

        promote: list[dict] = []
        retire: list[dict] = []
        needs_test: list[dict] = []
        for item in candidates:
            decision = self._classify(item, baseline, comparable_count=len(sufficient))
            item["decision"] = decision
            if decision == "promote":
                promote.append(item)
            elif decision == "retire":
                retire.append(item)
            else:
                needs_test.append(item)

        promote.sort(key=lambda item: item["metrics"]["weighted_score"], reverse=True)
        retire.sort(key=lambda item: item["metrics"]["weighted_score"])
        needs_test.sort(key=lambda item: item["metrics"]["weighted_score"], reverse=True)
        attribution_summary = self._attribution_summary(
            snapshots=snapshots,
            candidates=candidates,
            unmatched=unmatched,
        )
        next_generation = self._next_generation(
            promote=promote,
            retire=retire,
            needs_test=needs_test,
            attribution_summary=attribution_summary,
        )
        return {
            "project_id": self.project_id,
            "product_code": product_code,
            "window_days": window_days,
            "thresholds": {
                "min_impressions": MIN_IMPRESSIONS,
                "min_clicks": MIN_CLICKS,
                "min_spend": MIN_SPEND,
            },
            "baseline": baseline,
            "promote": promote,
            "retire": retire,
            "needs_test": needs_test,
            "unmatched": unmatched,
            "attribution_summary": attribution_summary,
            "next_generation": next_generation,
        }

    def _unmatched_item(self, snapshot: PerformanceSnapshot, attribution: dict) -> dict:
        metrics = snapshot.metrics or {}
        return {
            "creative_key": snapshot.creative_key,
            "snapshot_id": snapshot.id,
            "status": attribution.get("status") or "unattributed",
            "method": attribution.get("method") or "unknown",
            "warnings": attribution.get("warnings") or [],
            "metrics": self._metrics([metrics], [snapshot.weighted_score]),
        }

    def _candidate_item(self, creative_key: str, snapshots: list[PerformanceSnapshot]) -> dict:
        metrics_list = [snapshot.metrics or {} for snapshot in snapshots]
        weighted_scores = [snapshot.weighted_score or 0 for snapshot in snapshots]
        attribution = metrics_list[0].get("attribution") or {}
        variant = self.db.get(RunVariant, attribution.get("run_variant_id"))
        asset_id = attribution.get("variant_asset_id")
        asset = self.db.get(VariantAsset, asset_id) if asset_id else None
        run = self.db.get(PipelineRun, attribution.get("run_id") or (variant.run_id if variant else None))
        quality = self._quality(variant, asset)
        evidence = self._evidence(metrics_list)
        dimensions = self._dimensions(variant, asset, run)
        return {
            "creative_key": creative_key,
            "run_id": attribution.get("run_id"),
            "run_variant_id": attribution.get("run_variant_id"),
            "variant_asset_id": attribution.get("variant_asset_id"),
            "asset_type": attribution.get("asset_type"),
            "attribution": attribution,
            "dimensions": dimensions,
            "metrics": self._metrics(metrics_list, weighted_scores),
            "evidence": evidence,
            "quality": quality,
            "reasons": [],
        }

    def _metrics(self, metrics_list: list[dict], weighted_scores: list[float]) -> dict:
        impressions = sum(int(m.get("impressions", 0) or 0) for m in metrics_list)
        clicks = sum(int(m.get("clicks", 0) or 0) for m in metrics_list)
        spend = sum(float(m.get("spend", 0) or 0) for m in metrics_list)
        conversions = sum(int(m.get("conversions", 0) or 0) for m in metrics_list)
        revenue = sum(float(m.get("revenue", 0) or 0) for m in metrics_list)
        thumbstop_vals = [
            float((m.get("extra_metrics") or {}).get("thumbstop_rate", 0) or 0)
            for m in metrics_list
            if (m.get("extra_metrics") or {}).get("thumbstop_rate") is not None
        ]
        platforms = sorted({str(m.get("platform") or "").strip() for m in metrics_list if str(m.get("platform") or "").strip()})
        return {
            "impressions": impressions,
            "clicks": clicks,
            "spend": round(spend, 2),
            "conversions": conversions,
            "revenue": round(revenue, 2),
            "ctr": round(clicks / impressions, 6) if impressions > 0 else 0.0,
            "cvr": round(conversions / clicks, 6) if clicks > 0 else 0.0,
            "cpa": round(spend / conversions, 4) if conversions > 0 else 0.0,
            "roas": round(revenue / spend, 4) if spend > 0 else 0.0,
            "thumbstop_rate": round(sum(thumbstop_vals) / len(thumbstop_vals), 6) if thumbstop_vals else None,
            "weighted_score": round(sum(weighted_scores) / max(1, len(weighted_scores)), 2),
            "snapshots": len(metrics_list),
            "platforms": platforms,
        }

    def _evidence(self, metrics_list: list[dict]) -> dict:
        metrics = self._metrics(metrics_list, [0])
        missing = []
        if metrics["impressions"] < MIN_IMPRESSIONS:
            missing.append("impressions")
        if metrics["clicks"] < MIN_CLICKS:
            missing.append("clicks")
        if metrics["spend"] < MIN_SPEND:
            missing.append("spend")
        return {
            "sufficient": not missing,
            "missing": missing,
            "thresholds": {
                "impressions": MIN_IMPRESSIONS,
                "clicks": MIN_CLICKS,
                "spend": MIN_SPEND,
            },
        }

    def _quality(self, variant: RunVariant | None, asset: VariantAsset | None) -> dict:
        flags: list[str] = []
        blocking = False
        if asset and asset.failure_category:
            blocking = True
            flags.append(f"asset_failure:{asset.failure_category}")
        payload = asset.payload if asset else {}
        visual_qa = payload.get("visual_qa") if isinstance(payload, dict) and isinstance(payload.get("visual_qa"), dict) else {}
        if visual_qa.get("status") == "fail":
            blocking = True
            flags.append("visual_qa_failed")
        flags.extend(str(flag) for flag in visual_qa.get("flags") or [])
        scores: list[dict] = []
        if variant:
            rows = self.db.scalars(
                select(VariantScore)
                .where(VariantScore.run_variant_id == variant.id)
                .order_by(desc(VariantScore.created_at))
            ).all()
            for row in rows:
                level = str(row.compliance_level or "").lower()
                action = str(row.recommended_action or "").lower()
                if level in {"fail", "high", "pending"} or action in {"request_regeneration", "wait_for_asset"}:
                    blocking = True
                if action == "manual_review":
                    flags.append("manual_review_required")
                scores.append({
                    "score_type": row.score_type,
                    "total_score": row.total_score,
                    "compliance_level": row.compliance_level,
                    "recommended_action": row.recommended_action,
                })
        return {"blocking": blocking, "flags": sorted(set(flags)), "scores": scores}

    def _dimensions(self, variant: RunVariant | None, asset: VariantAsset | None, run: PipelineRun | None) -> dict:
        payload = asset.payload if asset else {}
        return {
            "product_code": run.product_code if run else None,
            "campaign_id": run.campaign_id if run else None,
            "angle": variant.angle if variant else "",
            "hook": variant.hook if variant else "",
            "selling_point": variant.message if variant else "",
            "visual_pattern": (payload or {}).get("prompt") if isinstance(payload, dict) else None,
            "video_structure": (payload or {}).get("structure") or (payload or {}).get("script_structure") if isinstance(payload, dict) else None,
        }

    def _baseline(self, items: list[dict]) -> dict:
        if not items:
            return {"weighted_score": 0.0, "ctr": 0.0, "cvr": 0.0, "count": 0}
        return {
            "weighted_score": round(sum(item["metrics"]["weighted_score"] for item in items) / len(items), 2),
            "ctr": round(sum(item["metrics"]["ctr"] for item in items) / len(items), 6),
            "cvr": round(sum(item["metrics"]["cvr"] for item in items) / len(items), 6),
            "count": len(items),
        }

    def _classify(self, item: dict, baseline: dict, *, comparable_count: int) -> str:
        metrics = item["metrics"]
        reasons = item["reasons"]
        if item["quality"]["blocking"]:
            reasons.append("production_quality_blocked")
            return "needs_test"
        if not item["evidence"]["sufficient"]:
            reasons.append("insufficient_data")
            return "needs_test"
        if comparable_count < 2:
            reasons.append("needs_comparable_creative")
            return "needs_test"
        baseline_ctr = baseline.get("ctr") or 0
        baseline_cvr = baseline.get("cvr") or 0
        if baseline_ctr and baseline_cvr and metrics["ctr"] >= baseline_ctr * 1.2 and metrics["cvr"] < baseline_cvr * 0.75:
            reasons.append("high_attention_low_intent")
            return "needs_test"
        baseline_score = baseline.get("weighted_score") or 0
        if baseline_score and metrics["weighted_score"] >= baseline_score * 1.1:
            reasons.append("above_peer_baseline")
            return "promote"
        if baseline_score and metrics["weighted_score"] <= baseline_score * 0.8:
            reasons.append("below_peer_baseline")
            return "retire"
        reasons.append("mixed_signal")
        return "needs_test"

    def _attribution_summary(
        self,
        *,
        snapshots: list[PerformanceSnapshot],
        candidates: list[dict],
        unmatched: list[dict],
    ) -> dict:
        total_snapshots = len(snapshots)
        attributed_snapshots = sum(int((item.get("metrics") or {}).get("snapshots") or 0) for item in candidates)
        unmatched_count = len(unmatched)
        return {
            "total_snapshots": total_snapshots,
            "strategy_safe_snapshots": attributed_snapshots,
            "unmatched_snapshots": unmatched_count,
            "strategy_safe_rate": round(attributed_snapshots / total_snapshots, 4) if total_snapshots else 0.0,
            "creative_count": len(candidates),
            "unmatched_methods": sorted({str(item.get("method") or "unknown") for item in unmatched}),
        }

    def _next_generation(
        self,
        *,
        promote: list[dict],
        retire: list[dict],
        needs_test: list[dict],
        attribution_summary: dict,
    ) -> dict:
        priority_seeds = [_generation_seed(item) for item in promote[:5]]
        avoid_seeds = [_generation_seed(item) for item in retire[:5]]
        test_queue = [_generation_seed(item) for item in needs_test[:5]]
        return {
            "summary": _generation_summary(priority_seeds, avoid_seeds, test_queue, attribution_summary),
            "priority_seeds": priority_seeds,
            "avoid_seeds": avoid_seeds,
            "test_queue": test_queue,
            "dimension_priorities": {
                "angles": _rank_dimension(promote, retire, "angle"),
                "hooks": _rank_dimension(promote, retire, "hook"),
                "asset_types": _rank_asset_types(promote, retire),
                "platforms": _rank_platforms(promote, retire),
            },
            "attribution_quality": {
                "strategy_safe_rate": attribution_summary.get("strategy_safe_rate", 0.0),
                "unmatched_snapshots": attribution_summary.get("unmatched_snapshots", 0),
                "recommendation": (
                    "improve_tracking"
                    if float(attribution_summary.get("strategy_safe_rate") or 0) < 0.8
                    else "tracking_ready"
                ),
            },
        }


def refresh_creative_decision_memory(
    db: Session,
    *,
    project_id: str,
    product_code: str | None = None,
    window_days: int = 30,
) -> tuple[dict, list[GmMemory]]:
    report = CreativeDecisionAnalyzer(db, project_id).decision_report(
        product_code=product_code,
        window_days=window_days,
    )
    rows_by_product: dict[str, dict[str, list[dict]]] = defaultdict(lambda: {"promote": [], "retire": []})
    for bucket in ("promote", "retire"):
        for item in report[bucket]:
            code = item.get("dimensions", {}).get("product_code")
            if code:
                rows_by_product[code][bucket].append(item)

    created: list[GmMemory] = []
    for code, buckets in rows_by_product.items():
        promote = buckets["promote"][:5]
        retire = buckets["retire"][:5]
        if not promote and not retire:
            continue
        score_hint = max([item["metrics"]["weighted_score"] for item in [*promote, *retire]] or [0])
        entry = GmMemory(
            project_id=project_id,
            memory_scope="product",
            product_code=code,
            source_type="creative_decision_attribution",
            score_hint=score_hint,
            memory_type="summary",
            content={
                "source": "creative_decision_attribution",
                "scope": "product",
                "product_code": code,
                "summary": "Use attributed creative performance to promote winning ideas and retire weak creative directions.",
                "promote": promote,
                "retire": retire,
                "next_generation": report.get("next_generation") or {},
                "attribution_summary": report.get("attribution_summary") or {},
                "winning_patterns": [_memory_pattern(item) for item in promote],
                "avoid_patterns": [_memory_pattern(item) for item in retire],
                "evidence": [{"source": "performance_snapshot", "window_days": window_days}],
                "metric_window": {"window_days": window_days},
                "confidence": round(min(0.95, 0.65 + 0.05 * len([*promote, *retire])), 2),
            },
        )
        db.add(entry)
        created.append(entry)
    db.flush()
    return report, created


def _memory_pattern(item: dict) -> dict:
    dimensions = item.get("dimensions") or {}
    metrics = item.get("metrics") or {}
    return {
        "creative_key": item.get("creative_key"),
        "decision": item.get("decision"),
        "angle": dimensions.get("angle"),
        "hook": dimensions.get("hook"),
        "selling_point": dimensions.get("selling_point"),
        "visual_pattern": dimensions.get("visual_pattern"),
        "video_structure": dimensions.get("video_structure"),
        "asset_type": item.get("asset_type"),
        "platforms": metrics.get("platforms") or [],
        "weighted_score": metrics.get("weighted_score"),
        "ctr": metrics.get("ctr"),
        "cvr": metrics.get("cvr"),
        "reasons": item.get("reasons") or [],
    }


def _generation_seed(item: dict) -> dict:
    dimensions = item.get("dimensions") or {}
    metrics = item.get("metrics") or {}
    return {
        "creative_key": item.get("creative_key"),
        "decision": item.get("decision"),
        "product_code": dimensions.get("product_code"),
        "angle": dimensions.get("angle"),
        "hook": dimensions.get("hook"),
        "selling_point": dimensions.get("selling_point"),
        "asset_type": item.get("asset_type"),
        "platforms": metrics.get("platforms") or [],
        "weighted_score": metrics.get("weighted_score"),
        "ctr": metrics.get("ctr"),
        "cvr": metrics.get("cvr"),
        "roas": metrics.get("roas"),
        "reasons": item.get("reasons") or [],
    }


def _generation_summary(
    priority_seeds: list[dict],
    avoid_seeds: list[dict],
    test_queue: list[dict],
    attribution_summary: dict,
) -> str:
    if priority_seeds:
        first = priority_seeds[0]
        return (
            f"Generate more variants around angle '{first.get('angle') or 'unknown'}' "
            f"and hook '{first.get('hook') or 'unknown'}'; avoid {len(avoid_seeds)} weak direction(s)."
        )
    if test_queue:
        return "Evidence is mixed; run controlled follow-up tests before scaling new creative directions."
    if attribution_summary.get("unmatched_snapshots"):
        return "Improve creative attribution before using performance data to steer generation."
    return "No attributed creative performance is ready to steer generation."


def _rank_dimension(promote: list[dict], retire: list[dict], dimension_key: str) -> list[dict]:
    buckets: dict[str, dict] = defaultdict(lambda: {"value": "", "promote": 0, "retire": 0, "score_sum": 0.0, "count": 0})
    for decision, rows in (("promote", promote), ("retire", retire)):
        for item in rows:
            value = str((item.get("dimensions") or {}).get(dimension_key) or "").strip()
            if not value:
                continue
            bucket = buckets[value]
            bucket["value"] = value
            bucket[decision] += 1
            bucket["score_sum"] += float((item.get("metrics") or {}).get("weighted_score") or 0)
            bucket["count"] += 1
    ranked = []
    for bucket in buckets.values():
        count = int(bucket["count"] or 1)
        ranked.append({
            "value": bucket["value"],
            "promote": bucket["promote"],
            "retire": bucket["retire"],
            "avg_weighted_score": round(float(bucket["score_sum"]) / count, 2),
            "net_signal": int(bucket["promote"]) - int(bucket["retire"]),
        })
    return sorted(ranked, key=lambda item: (item["net_signal"], item["avg_weighted_score"]), reverse=True)[:8]


def _rank_asset_types(promote: list[dict], retire: list[dict]) -> list[dict]:
    return _rank_item_values(promote, retire, lambda item: [str(item.get("asset_type") or "creative")])


def _rank_platforms(promote: list[dict], retire: list[dict]) -> list[dict]:
    return _rank_item_values(promote, retire, lambda item: (item.get("metrics") or {}).get("platforms") or ["unknown"])


def _rank_item_values(promote: list[dict], retire: list[dict], values_fn) -> list[dict]:
    buckets: dict[str, dict] = defaultdict(lambda: {"value": "", "promote": 0, "retire": 0})
    for decision, rows in (("promote", promote), ("retire", retire)):
        for item in rows:
            for value in values_fn(item):
                value = str(value or "").strip()
                if not value:
                    continue
                buckets[value]["value"] = value
                buckets[value][decision] += 1
    ranked = [
        {
            "value": bucket["value"],
            "promote": bucket["promote"],
            "retire": bucket["retire"],
            "net_signal": int(bucket["promote"]) - int(bucket["retire"]),
        }
        for bucket in buckets.values()
    ]
    return sorted(ranked, key=lambda item: (item["net_signal"], item["promote"]), reverse=True)[:8]

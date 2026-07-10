from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.data.models import (
    FeedbackImport,
    GmMemory,
    GmInstructionVersion,
    PerformanceSnapshot,
    PipelineRun,
    Project,
    RunVariant,
    VariantAsset,
    VariantReview,
    Workspace,
)
from app.schemas.contracts import FeedbackRow
from app.services.creative_attribution import (
    resolve_campaign_id,
    resolve_performance_attribution,
    product_code_from_campaign,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _weighted_score(
    *,
    ctr: float,
    cpc: float,
    cpa: float,
    roas: float,
    weights: dict,
) -> float:
    ctr_score = min(100.0, ctr * 1000.0)
    cpc_score = max(0.0, 100.0 / (1.0 + max(0.0, cpc)))
    cpa_score = max(0.0, 100.0 / (1.0 + max(0.0, cpa)))
    roas_score = min(100.0, roas * 30.0)
    return round(
        ctr_score * float(weights.get("ctr", 0.35))
        + cpc_score * float(weights.get("cpc", 0.15))
        + cpa_score * float(weights.get("cpa", 0.30))
        + roas_score * float(weights.get("roas", 0.20)),
        2,
    )


def _metric_window(rows: list[FeedbackRow]) -> dict:
    starts = [row.period_start.isoformat() for row in rows if row.period_start]
    ends = [row.period_end.isoformat() for row in rows if row.period_end]
    return {"start": min(starts) if starts else None, "end": max(ends) if ends else None}


def _get_workspace_project(db: Session, workspace_name: str, project_name: str) -> tuple[Workspace, Project]:
    workspace = db.scalar(select(Workspace).where(Workspace.name == workspace_name))
    if not workspace:
        workspace = Workspace(name=workspace_name)
        db.add(workspace)
        db.flush()
    project = db.scalar(select(Project).where(Project.workspace_id == workspace.id, Project.name == project_name))
    if not project:
        project = Project(workspace_id=workspace.id, name=project_name)
        db.add(project)
        db.flush()
    return workspace, project


def _latest_variant_asset(run_variant_id: str, asset_type: str, db: Session) -> VariantAsset | None:
    return db.scalar(
        select(VariantAsset)
        .where(VariantAsset.run_variant_id == run_variant_id, VariantAsset.asset_type == asset_type)
        .order_by(desc(VariantAsset.created_at))
        .limit(1)
    )


def _variant_pattern_payload(db: Session, variant: RunVariant | None) -> dict:
    if not variant:
        return {}
    copy_asset = _latest_variant_asset(variant.id, "copy", db)
    image_asset = _latest_variant_asset(variant.id, "image", db)
    script_asset = _latest_variant_asset(variant.id, "video_script", db)
    image_payload = (image_asset.payload or {}) if image_asset else {}
    platform_readiness = {}
    if image_asset:
        platform_readiness = image_payload.get("platform_readiness") or (image_payload.get("marketplace_qa") or {}).get("platform_readiness") or {}
    reviews = db.scalars(
        select(VariantReview).where(VariantReview.run_variant_id == variant.id).order_by(desc(VariantReview.created_at))
    ).all()
    review_tags = sorted({tag for review in reviews for tag in (review.tags or [])})
    return {
        "variant_id": variant.variant_id,
        "angle": variant.angle,
        "hook": variant.hook,
        "message": variant.message,
        "visual_pattern": image_payload.get("prompt") if image_asset else None,
        "image_uri": image_asset.uri if image_asset else None,
        "image_role": image_payload.get("image_role") if image_asset else None,
        "marketplace_qa_status": (image_payload.get("marketplace_qa") or {}).get("status") if image_asset else None,
        "platform_readiness": platform_readiness,
        "visual_review_tags": review_tags,
        "copy_pattern": ((copy_asset.payload or {}).get("headline") if copy_asset else None),
        "script_pattern": ((script_asset.payload or {}).get("hook") if script_asset else None),
    }


def import_feedback_rows(
    db: Session,
    *,
    workspace_name: str,
    project_name: str,
    rows: list[FeedbackRow],
    file_name: str,
) -> tuple[FeedbackImport, int, GmMemory | None]:
    workspace, project = _get_workspace_project(db, workspace_name, project_name)
    import_record = FeedbackImport(
        workspace_id=workspace.id,
        project_id=project.id,
        file_name=file_name,
        row_count=len(rows),
        raw_rows=[row.model_dump(mode="json") for row in rows],
    )
    db.add(import_record)

    snapshot_count = 0
    scored_rows: list[tuple[str, float, dict]] = []
    memory_by_product: dict[str, list[tuple[str, float, dict]]] = {}
    memory_by_industry: dict[str, list[tuple[str, float, dict]]] = {}
    for row in rows:
        ctr = _safe_div(row.clicks, row.impressions)
        cpc = _safe_div(row.spend, row.clicks)
        cpa = _safe_div(row.spend, row.conversions)
        roas = _safe_div(row.revenue, row.spend)
        weighted = _weighted_score(ctr=ctr, cpc=cpc, cpa=cpa, roas=roas, weights=project.metric_weights)
        run_model = db.get(PipelineRun, row.run_id) if row.run_id else None
        campaign_id = run_model.campaign_id if run_model else None
        campaign_id = campaign_id or resolve_campaign_id(
            db,
            project_id=project.id,
            campaign_name=row.campaign_name,
            platform_campaign_id=row.platform_campaign_id,
        )
        product_code = run_model.product_code if run_model else (row.product_code or "")
        product_code = product_code or (product_code_from_campaign(db, campaign_id) or "")
        industry_code = run_model.industry_code if run_model else (row.industry_code or "")
        attribution = resolve_performance_attribution(
            db,
            project_id=project.id,
            creative_key=row.creative_key,
            run_id=row.run_id,
            variant_id=row.variant_id,
            asset_type=row.asset_type,
            platform_ad_id=row.platform_ad_id,
            platform_creative_id=row.platform_creative_id,
            campaign_id=campaign_id,
            product_code=product_code or None,
            period_start=row.period_start,
            period_end=row.period_end,
        )
        resolved_creative_key = attribution.creative_key or row.creative_key
        resolved_run_id = attribution.run_id or row.run_id
        pattern_payload = _variant_pattern_payload(db, attribution.run_variant)
        if attribution.strategy_safe:
            scored_rows.append((resolved_creative_key, weighted, pattern_payload))
            if product_code:
                memory_by_product.setdefault(product_code, []).append((resolved_creative_key, weighted, pattern_payload))
            if industry_code:
                memory_by_industry.setdefault(industry_code, []).append((resolved_creative_key, weighted, pattern_payload))

        snapshot = PerformanceSnapshot(
            project_id=project.id,
            campaign_id=campaign_id,
            run_id=resolved_run_id,
            creative_key=resolved_creative_key,
            metrics={
                "impressions": row.impressions,
                "clicks": row.clicks,
                "spend": row.spend,
                "conversions": row.conversions,
                "revenue": row.revenue,
                "ctr": ctr,
                "cpc": cpc,
                "cpa": cpa,
                "roas": roas,
                "asset_type": attribution.asset_type or row.asset_type,
                "platform": row.platform,
                "platform_campaign_id": row.platform_campaign_id,
                "platform_ad_id": row.platform_ad_id,
                "platform_creative_id": row.platform_creative_id,
                "extra_metrics": row.extra_metrics,
                "attribution": attribution.metadata(),
            },
            weighted_score=weighted,
            period_start=row.period_start,
            period_end=row.period_end,
        )
        db.add(snapshot)
        snapshot_count += 1

    memory = None
    memory_entries: list[GmMemory] = []
    if scored_rows:
        scored_rows.sort(key=lambda item: item[1], reverse=True)
        top = scored_rows[:3]
        bottom = scored_rows[-3:]
        metric_window = _metric_window(rows)
        for product_code, items in memory_by_product.items():
            ranked = sorted(items, key=lambda item: item[1], reverse=True)
            top_product = ranked[:3]
            bottom_product = ranked[-3:]
            entry = GmMemory(
                project_id=project.id,
                memory_scope="product",
                product_code=product_code,
                source_type="feedback_import",
                score_hint=top_product[0][1] if top_product else None,
                memory_type="summary",
                content={
                    "source": "weekly_csv_import",
                    "scope": "product",
                    "product_code": product_code,
                    "top_variants": [
                        {"variant_id": variant_id, "weighted_score": score, "pattern": pattern}
                        for variant_id, score, pattern in top_product
                    ],
                    "underperformers": [
                        {"variant_id": variant_id, "weighted_score": score, "pattern": pattern}
                        for variant_id, score, pattern in bottom_product
                    ],
                    "summary": "Preserve product-level winning hook, visual, and script patterns and retire low-score variants.",
                    "winning_patterns": [item[2] or {"variant_id": item[0]} for item in top_product],
                    "avoid_patterns": [item[2] or {"variant_id": item[0]} for item in bottom_product],
                    "evidence": [{"source": "feedback_import", "file_name": file_name, "row_count": len(items)}],
                    "metric_window": metric_window,
                    "confidence": round(min(0.95, 0.5 + 0.05 * len(items)), 2),
                },
            )
            db.add(entry)
            memory_entries.append(entry)

        for industry_code, items in memory_by_industry.items():
            ranked = sorted(items, key=lambda item: item[1], reverse=True)
            top_industry = ranked[:3]
            bottom_industry = ranked[-3:]
            entry = GmMemory(
                project_id=project.id,
                memory_scope="industry",
                industry_code=industry_code,
                source_type="feedback_import",
                score_hint=top_industry[0][1] if top_industry else None,
                memory_type="summary",
                content={
                    "source": "weekly_csv_import",
                    "scope": "industry",
                    "industry_code": industry_code,
                    "top_variants": [
                        {"variant_id": variant_id, "weighted_score": score, "pattern": pattern}
                        for variant_id, score, pattern in top_industry
                    ],
                    "underperformers": [
                        {"variant_id": variant_id, "weighted_score": score, "pattern": pattern}
                        for variant_id, score, pattern in bottom_industry
                    ],
                    "summary": "Keep industry-level winning angle and visual/script patterns, avoid repeated low-performing variants.",
                    "winning_patterns": [item[2] or {"variant_id": item[0]} for item in top_industry],
                    "avoid_patterns": [item[2] or {"variant_id": item[0]} for item in bottom_industry],
                    "evidence": [{"source": "feedback_import", "file_name": file_name, "row_count": len(items)}],
                    "metric_window": metric_window,
                    "confidence": round(min(0.95, 0.5 + 0.05 * len(items)), 2),
                },
            )
            db.add(entry)
            memory_entries.append(entry)
        memory = memory_entries[0] if memory_entries else None
        latest_version = db.scalar(
            select(GmInstructionVersion.version)
            .where(GmInstructionVersion.project_id == project.id)
            .order_by(GmInstructionVersion.version.desc())
            .limit(1)
        )
        next_version = int(latest_version or 0) + 1
        db.add(
            GmInstructionVersion(
                project_id=project.id,
                source_feedback_import_id=import_record.id,
                version=next_version,
                content={
                    "version": next_version,
                    "source": "feedback_import",
                    "winning_patterns": [item[2] or {"variant_id": item[0]} for item in top],
                    "avoid_patterns": [item[2] or {"variant_id": item[0]} for item in bottom],
                    "product_memory_count": len(memory_by_product),
                    "industry_memory_count": len(memory_by_industry),
                    "guidance": "Prioritize winning hooks and avoid low-performing patterns in planning stage.",
                },
                is_active=True,
            )
        )
    db.flush()
    return import_record, snapshot_count, memory


def project_leaderboard(db: Session, project_id: str, limit: int = 20) -> list[dict]:
    snapshots = db.scalars(
        select(PerformanceSnapshot)
        .where(PerformanceSnapshot.project_id == project_id)
        .order_by(desc(PerformanceSnapshot.created_at))
    ).all()
    merged: dict[str, dict] = {}
    for snap in snapshots:
        item = merged.setdefault(
            snap.creative_key,
            {"creative_key": snap.creative_key, "weighted_sum": 0.0, "count": 0, "metrics": []},
        )
        item["weighted_sum"] += snap.weighted_score
        item["count"] += 1
        item["metrics"].append(snap.metrics)

    ranked = []
    for creative_key, item in merged.items():
        count = max(1, item["count"])
        weighted = item["weighted_sum"] / count
        ctr = sum(m.get("ctr", 0) for m in item["metrics"]) / count
        cpc = sum(m.get("cpc", 0) for m in item["metrics"]) / count
        cpa = sum(m.get("cpa", 0) for m in item["metrics"]) / count
        roas = sum(m.get("roas", 0) for m in item["metrics"]) / count
        recommendation = "keep_and_scale" if weighted >= 60 else "retire_or_rework"
        ranked.append(
            {
                "creative_key": creative_key,
                "weighted_score": round(weighted, 2),
                "ctr": round(ctr, 4),
                "cpc": round(cpc, 4),
                "cpa": round(cpa, 4),
                "roas": round(roas, 4),
                "recommendation": recommendation,
            }
        )
    ranked.sort(key=lambda item: item["weighted_score"], reverse=True)
    return ranked[:limit]

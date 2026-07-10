from __future__ import annotations

import csv
import io
from datetime import date
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.data.models import GmMemory, PerformanceSnapshot, Product
from app.integrations.sync_service import _get_or_create_workspace_project, _utcnow
from app.schemas.contracts import FeedbackRow
from app.services.feedback import import_feedback_rows


def import_offline_store_csv(
    db: Session,
    *,
    workspace_name: str,
    project_name: str,
    platform: str,
    file_name: str,
    content: bytes,
) -> dict:
    platform = platform.lower().strip()
    if platform not in {"shopify", "meta"}:
        raise ValueError("offline CSV platform must be shopify or meta")
    workspace, project = _get_or_create_workspace_project(db, workspace_name, project_name)
    rows = _parse_csv(content)
    _validate_platform_rows(platform, rows)
    batch_id = f"offline-{platform}-{uuid.uuid4()}"
    products_seen = 0
    product_metrics: dict[str, dict] = {}
    feedback_rows: list[FeedbackRow] = []

    for row in rows:
        product_code = _first(row, "product_code", "sku", "variant_sku", "handle")
        product_name = _first(row, "product_name", "name", "title") or product_code
        if product_code:
            _upsert_product(db, project_id=project.id, product_code=product_code, product_name=product_name)
            products_seen += 1

        revenue = _float(_first(row, "total_revenue", "revenue", "sales", "gmv"))
        quantity = _int(_first(row, "total_quantity", "quantity", "units", "units_sold", "orders"))
        order_date = _date(_first(row, "date", "order_date", "period_start"))
        if product_code and (revenue > 0 or quantity > 0):
            agg = product_metrics.setdefault(
                product_code,
                {"total_revenue": 0.0, "total_quantity": 0, "dates": set()},
            )
            agg["total_revenue"] += revenue
            agg["total_quantity"] += quantity
            if order_date:
                agg["dates"].add(order_date.isoformat())

        impressions = _int(_first(row, "impressions", "imps"))
        clicks = _int(_first(row, "clicks"))
        spend = _float(_first(row, "spend", "cost"))
        conversions = _int(_first(row, "conversions", "purchases", "orders"))
        creative_key = _first(row, "creative_key", "ad_creative_id", "creative_id", "ad_id")
        has_performance = any(value > 0 for value in (impressions, clicks, spend, conversions))
        if creative_key and has_performance:
            feedback_rows.append(
                FeedbackRow(
                    project_name=project_name,
                    creative_key=creative_key,
                    variant_id=_first(row, "variant_id"),
                    asset_type=_first(row, "asset_type"),
                    campaign_name=_first(row, "campaign_name"),
                    run_id=_first(row, "run_id"),
                    impressions=impressions,
                    clicks=clicks,
                    spend=spend,
                    conversions=conversions,
                    revenue=_float(_first(row, "ad_revenue", "attributed_revenue")) or revenue,
                    period_start=order_date,
                    period_end=_date(_first(row, "period_end")),
                    platform=_first(row, "platform") or platform,
                    platform_campaign_id=_first(row, "platform_campaign_id", "campaign_id"),
                    platform_ad_id=_first(row, "platform_ad_id", "ad_id"),
                    platform_creative_id=_first(row, "platform_creative_id", "creative_id"),
                    product_code=product_code or None,
                    industry_code=workspace.industry_code or None,
                    extra_metrics={
                        "source": "offline_csv_import",
                        "offline_platform": platform,
                        "offline_batch_id": batch_id,
                        "file_name": file_name,
                        "thumbstop_rate": _float(_first(row, "thumbstop_rate", "three_second_view_rate")),
                    },
                )
            )

    memory_count = _write_store_memories(
        db,
        workspace_id=workspace.id,
        workspace_name=workspace.name,
        project_id=project.id,
        product_metrics=product_metrics,
        platform=platform,
        batch_id=batch_id,
        file_name=file_name,
    )

    snapshots_created = 0
    feedback_memory_id = None
    if feedback_rows:
        _, snapshots_created, feedback_memory = import_feedback_rows(
            db,
            workspace_name=workspace_name,
            project_name=project_name,
            rows=feedback_rows,
            file_name=file_name,
        )
        feedback_memory_id = feedback_memory.id if feedback_memory else None
        for snapshot in db.scalars(
            select(PerformanceSnapshot)
            .where(PerformanceSnapshot.project_id == project.id)
            .order_by(PerformanceSnapshot.created_at.desc())
            .limit(len(feedback_rows))
        ).all():
            metrics = dict(snapshot.metrics or {})
            extra = dict(metrics.get("extra_metrics") or {})
            if extra.get("offline_batch_id") == batch_id:
                metrics["offline_batch_id"] = batch_id
                metrics["offline_platform"] = platform
                metrics["source_type"] = "offline_csv_import"
                snapshot.metrics = metrics

    return {
        "batch_id": batch_id,
        "platform": platform,
        "rows": len(rows),
        "products_seen": products_seen,
        "product_memory_count": memory_count["product"],
        "shop_memory_count": memory_count["shop"],
        "performance_rows": len(feedback_rows),
        "snapshots_created": snapshots_created,
        "feedback_memory_id": feedback_memory_id,
    }


def _validate_platform_rows(platform: str, rows: list[dict[str, str]]) -> None:
    if not rows:
        raise ValueError("CSV has no data rows")
    headers = {key.lower().strip() for row in rows for key in row}
    if platform == "shopify":
        _require_any(headers, {"product_code", "sku", "variant_sku", "handle"}, "Shopify CSV requires product_code, sku, variant_sku, or handle")
        _require_any(headers, {"total_revenue", "revenue", "sales", "gmv", "total_quantity", "quantity", "units", "units_sold", "orders"}, "Shopify CSV requires revenue or quantity columns")
        if not any(
            _first(row, "product_code", "sku", "variant_sku", "handle")
            and (_float(_first(row, "total_revenue", "revenue", "sales", "gmv")) > 0 or _int(_first(row, "total_quantity", "quantity", "units", "units_sold", "orders")) > 0)
            for row in rows
        ):
            raise ValueError("Shopify CSV contains no usable product revenue or quantity rows")
        return
    _require_any(headers, {"creative_key", "ad_creative_id", "creative_id", "ad_id"}, "Meta CSV requires creative_key, ad_creative_id, creative_id, or ad_id")
    _require_any(headers, {"impressions", "imps"}, "Meta CSV requires impressions")
    _require_any(headers, {"clicks"}, "Meta CSV requires clicks")
    _require_any(headers, {"spend", "cost"}, "Meta CSV requires spend")
    if not any(
        _first(row, "creative_key", "ad_creative_id", "creative_id", "ad_id")
        and (
            _int(_first(row, "impressions", "imps")) > 0
            or _int(_first(row, "clicks")) > 0
            or _float(_first(row, "spend", "cost")) > 0
            or _int(_first(row, "conversions", "purchases", "orders")) > 0
        )
        for row in rows
    ):
        raise ValueError("Meta CSV contains no usable creative performance rows")


def _require_any(headers: set[str], candidates: set[str], message: str) -> None:
    if not headers.intersection(candidates):
        raise ValueError(message)


def _parse_csv(content: bytes) -> list[dict[str, str]]:
    text = content.decode("utf-8-sig", errors="ignore")
    reader = csv.DictReader(io.StringIO(text))
    return [{str(k or "").strip(): str(v or "").strip() for k, v in row.items()} for row in reader]


def _first(row: dict[str, str], *keys: str) -> str:
    lowered = {key.lower().strip(): value for key, value in row.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _float(value: str) -> float:
    try:
        return float(str(value or "").replace(",", "").replace("$", ""))
    except ValueError:
        return 0.0


def _int(value: str) -> int:
    try:
        return int(float(str(value or "").replace(",", "")))
    except ValueError:
        return 0


def _date(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _upsert_product(db: Session, *, project_id: str, product_code: str, product_name: str) -> None:
    product = db.scalar(
        select(Product).where(Product.project_id == project_id, Product.product_code == product_code)
    )
    if not product:
        product = Product(project_id=project_id, name=product_name or product_code, product_code=product_code)
        db.add(product)
        db.flush()
        return
    if product_name and product.name != product_name:
        product.name = product_name


def _write_store_memories(
    db: Session,
    *,
    workspace_id: str,
    workspace_name: str,
    project_id: str,
    product_metrics: dict[str, dict],
    platform: str,
    batch_id: str,
    file_name: str,
) -> dict[str, int]:
    product_count = 0
    all_dates: set[str] = set()
    total_revenue = 0.0
    total_quantity = 0
    for product_code, agg in product_metrics.items():
        dates = sorted(agg["dates"])
        all_dates.update(dates)
        revenue = float(agg["total_revenue"])
        quantity = int(agg["total_quantity"])
        total_revenue += revenue
        total_quantity += quantity
        active_days = max(len(dates), 1)
        db.add(
            GmMemory(
                project_id=project_id,
                memory_scope="product",
                product_code=product_code,
                source_type="offline_csv_import",
                memory_type="summary",
                score_hint=round(revenue / active_days, 2),
                content={
                    "source": "offline_csv_import",
                    "offline_platform": platform,
                    "offline_batch_id": batch_id,
                    "scope": "product",
                    "product_code": product_code,
                    "total_revenue": round(revenue, 2),
                    "total_quantity": quantity,
                    "daily_avg_revenue": round(revenue / active_days, 2),
                    "daily_avg_quantity": round(quantity / active_days, 2),
                    "active_order_days": len(dates),
                    "synced_at": _utcnow().isoformat(),
                    "summary": f"Offline CSV product {product_code}: ${revenue:.2f} uploaded revenue, {quantity} units.",
                    "winning_patterns": [],
                    "avoid_patterns": [],
                    "evidence": [{"source": "offline_csv_import", "platform": platform, "file_name": file_name, "batch_id": batch_id}],
                    "metric_window": {"start": dates[0] if dates else None, "end": dates[-1] if dates else None},
                    "confidence": round(min(0.9, 0.5 + 0.05 * active_days), 2),
                },
            )
        )
        product_count += 1

    if not product_metrics:
        return {"product": 0, "shop": 0}

    sorted_dates = sorted(all_dates)
    active_days = max(len(sorted_dates), 1)
    db.add(
        GmMemory(
            project_id=project_id,
            memory_scope="shop",
            source_type="offline_csv_import",
            memory_type="summary",
            score_hint=round(total_revenue / active_days, 2),
            content={
                "source": "offline_csv_import",
                "offline_platform": platform,
                "offline_batch_id": batch_id,
                "scope": "shop",
                "shop_id": workspace_id,
                "shop_name": workspace_name,
                "total_revenue": round(total_revenue, 2),
                "total_quantity": total_quantity,
                "daily_avg_revenue": round(total_revenue / active_days, 2),
                "active_order_days": len(sorted_dates),
                "product_count": len(product_metrics),
                "synced_at": _utcnow().isoformat(),
                "summary": f"Offline CSV store: ${total_revenue:.2f} uploaded revenue across {len(product_metrics)} products.",
                "winning_patterns": [],
                "avoid_patterns": [],
                "evidence": [{"source": "offline_csv_import", "platform": platform, "file_name": file_name, "product_count": len(product_metrics), "batch_id": batch_id}],
                "metric_window": {"start": sorted_dates[0] if sorted_dates else None, "end": sorted_dates[-1] if sorted_dates else None},
                "confidence": round(min(0.9, 0.5 + 0.05 * active_days), 2),
            },
        )
    )
    return {"product": product_count, "shop": 1}


def list_offline_csv_batches(db: Session, *, workspace_name: str, project_name: str) -> list[dict]:
    workspace, project = _get_or_create_workspace_project(db, workspace_name, project_name)
    batches: dict[str, dict] = {}
    rows = db.scalars(
        select(GmMemory)
        .where(GmMemory.project_id == project.id, GmMemory.source_type == "offline_csv_import")
        .order_by(GmMemory.created_at.desc())
        .limit(200)
    ).all()
    for row in rows:
        content = row.content or {}
        batch_id = content.get("offline_batch_id")
        if not batch_id:
            continue
        item = batches.setdefault(
            batch_id,
            {
                "batch_id": batch_id,
                "platform": content.get("offline_platform") or "unknown",
                "workspace_name": workspace.name,
                "project_name": project.name,
                "memory_count": 0,
                "total_revenue": 0.0,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            },
        )
        item["memory_count"] += 1
        item["total_revenue"] = max(item["total_revenue"], float(content.get("total_revenue") or 0))
    snapshots = db.scalars(
        select(PerformanceSnapshot)
        .where(PerformanceSnapshot.project_id == project.id)
        .order_by(PerformanceSnapshot.created_at.desc())
        .limit(500)
    ).all()
    for snapshot in snapshots:
        metrics = snapshot.metrics or {}
        extra = metrics.get("extra_metrics") or {}
        batch_id = metrics.get("offline_batch_id") or extra.get("offline_batch_id")
        if not batch_id:
            continue
        item = batches.setdefault(
            batch_id,
            {
                "batch_id": batch_id,
                "platform": metrics.get("offline_platform") or extra.get("offline_platform") or "unknown",
                "workspace_name": workspace.name,
                "project_name": project.name,
                "memory_count": 0,
                "snapshot_count": 0,
                "total_revenue": 0.0,
                "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
            },
        )
        item["snapshot_count"] = int(item.get("snapshot_count") or 0) + 1
        item["total_revenue"] = max(item["total_revenue"], float(metrics.get("revenue") or 0))
    for item in batches.values():
        item.setdefault("snapshot_count", 0)
    return list(batches.values())


def delete_offline_csv_batch(db: Session, *, workspace_name: str, project_name: str, batch_id: str) -> dict:
    _, project = _get_or_create_workspace_project(db, workspace_name, project_name)
    memory_rows = db.scalars(
        select(GmMemory).where(GmMemory.project_id == project.id, GmMemory.source_type == "offline_csv_import")
    ).all()
    memory_ids = [
        row.id for row in memory_rows
        if (row.content or {}).get("offline_batch_id") == batch_id
    ]
    snapshot_rows = db.scalars(
        select(PerformanceSnapshot).where(PerformanceSnapshot.project_id == project.id)
    ).all()
    snapshot_ids = [
        row.id for row in snapshot_rows
        if (row.metrics or {}).get("offline_batch_id") == batch_id
        or ((row.metrics or {}).get("extra_metrics") or {}).get("offline_batch_id") == batch_id
    ]
    if memory_ids:
        db.execute(delete(GmMemory).where(GmMemory.id.in_(memory_ids)))
    if snapshot_ids:
        db.execute(delete(PerformanceSnapshot).where(PerformanceSnapshot.id.in_(snapshot_ids)))
    db.flush()
    return {"batch_id": batch_id, "memory_deleted": len(memory_ids), "snapshots_deleted": len(snapshot_ids)}

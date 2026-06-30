from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, UTC

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.models import (
    Campaign,
    GmMemory,
    IntegrationSync,
    Product,
    Project,
    Workspace,
)
from app.integrations.shopify import ShopifyProvider
from app.integrations.meta import MetaProvider
from app.integrations.models import SyncResult
from app.schemas.contracts import FeedbackRow

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _get_or_create_workspace_project(
    db: Session, workspace_name: str, project_name: str
) -> tuple[Workspace, Project]:
    workspace = db.scalar(select(Workspace).where(Workspace.name == workspace_name))
    if not workspace:
        workspace = Workspace(name=workspace_name)
        db.add(workspace)
        db.flush()
    project = db.scalar(
        select(Project).where(
            Project.workspace_id == workspace.id, Project.name == project_name
        )
    )
    if not project:
        project = Project(workspace_id=workspace.id, name=project_name)
        db.add(project)
        db.flush()
    return workspace, project


def _make_slug(value: str) -> str:
    import re

    slug = value.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


async def sync_shopify(
    db: Session,
    *,
    workspace_name: str,
    project_name: str,
    sync_type: str = "all",
    store_domain: str = "",
    access_token: str = "",
) -> SyncResult:
    import os

    domain = store_domain or os.getenv("CRISPY_API_KEY_SHOPIFY_DOMAIN", "")
    token = access_token or os.getenv("CRISPY_API_KEY_SHOPIFY", "")
    if not domain or not token:
        raise ValueError("Shopify store_domain and access_token are required")

    workspace, project = _get_or_create_workspace_project(db, workspace_name, project_name)

    sync_record = IntegrationSync(
        workspace_id=workspace.id,
        project_id=project.id,
        platform="shopify",
        sync_type=sync_type,
        status="running",
    )
    db.add(sync_record)
    db.flush()

    provider = ShopifyProvider(
        config={"store_domain": domain, "access_token": token}
    )
    items_synced = 0
    memory_count = 0

    try:
        if sync_type in ("products", "all"):
            products = await provider.fetch_products()
            for sp in products:
                skus = [v["sku"] for v in sp.variants if v.get("sku")]
                existing = None
                for sku in skus:
                    existing = db.scalar(
                        select(Product).where(
                            Product.project_id == project.id,
                            Product.product_code == sku,
                        )
                    )
                    if existing:
                        break
                if not existing:
                    code = skus[0] if skus else _make_slug(sp.handle)
                    final_code = code
                    counter = 1
                    while db.scalar(
                        select(Product).where(
                            Product.project_id == project.id,
                            Product.product_code == final_code,
                        )
                    ):
                        final_code = f"{code}-{counter}"
                        counter += 1
                    existing = Product(
                        project_id=project.id,
                        name=sp.title,
                        product_code=final_code,
                    )
                    db.add(existing)
                    db.flush()

                meta = dict(existing.metadata_json or {})
                meta["shopify_product_id"] = sp.shopify_product_id
                meta["shopify_handle"] = sp.handle
                meta["shopify_vendor"] = sp.vendor
                meta["shopify_product_type"] = sp.product_type
                meta["shopify_tags"] = sp.tags
                if sp.images:
                    meta["shopify_image"] = sp.images[0]["src"]
                existing.metadata_json = meta
                items_synced += 1

        if sync_type in ("orders", "all"):
            orders = await provider.fetch_orders()
            by_product: dict[str, dict] = {}
            for order in orders:
                for item in order.line_items:
                    sku = item.variant_sku or ""
                    variant_id = item.variant_id or ""
                    key = sku or f"vid_{variant_id}"
                    if not key:
                        continue
                    agg = by_product.setdefault(key, {
                        "total_revenue": 0.0,
                        "total_quantity": 0,
                        "order_dates": [],
                    })
                    agg["total_revenue"] += item.price * item.quantity
                    agg["total_quantity"] += item.quantity
                    if order.created_at:
                        agg["order_dates"].append(order.created_at[:10])

            today = date.today()
            for key, agg in by_product.items():
                product = db.scalar(
                    select(Product).where(
                        Product.project_id == project.id,
                        Product.product_code == key,
                    )
                )
                if not product:
                    continue
                distinct_days = len(set(agg["order_dates"]))
                active_days = max(distinct_days, 1)
                daily_avg_revenue = agg["total_revenue"] / active_days
                daily_avg_quantity = agg["total_quantity"] / active_days
                order_dates = sorted(set(agg["order_dates"]))

                past_data = (
                    db.scalars(
                        select(GmMemory)
                        .where(
                            GmMemory.project_id == project.id,
                            GmMemory.memory_scope == "product",
                            GmMemory.product_code == key,
                            GmMemory.source_type == "shopify_sync",
                        )
                        .order_by(GmMemory.created_at.desc())
                        .limit(1)
                    ).first()
                )
                prev_total = 0.0
                if past_data:
                    prev_total = float((past_data.content or {}).get("total_revenue", 0))

                entry = GmMemory(
                    project_id=project.id,
                    memory_scope="product",
                    product_code=key,
                    source_type="shopify_sync",
                    memory_type="summary",
                    score_hint=round(daily_avg_revenue, 2),
                    content={
                        "source": "shopify_sync",
                        "scope": "product",
                        "product_code": key,
                        "total_revenue": round(agg["total_revenue"], 2),
                        "total_quantity": agg["total_quantity"],
                        "daily_avg_revenue": round(daily_avg_revenue, 2),
                        "daily_avg_quantity": round(daily_avg_quantity, 2),
                        "previous_total_revenue": round(prev_total, 2),
                        "revenue_change_pct": (
                            round((agg["total_revenue"] - prev_total) / prev_total * 100, 1)
                            if prev_total > 0
                            else None
                        ),
                        "active_order_days": distinct_days,
                        "synced_at": _utcnow().isoformat(),
                        "summary": (
                            f"Product {key}: ${agg['total_revenue']:.2f} total revenue, "
                            f"{agg['total_quantity']} units sold over {distinct_days} active days."
                        ),
                        "winning_patterns": [],
                        "avoid_patterns": [],
                        "evidence": [{"source": "shopify_sync", "sync_id": sync_record.id, "active_order_days": distinct_days}],
                        "metric_window": {
                            "start": order_dates[0] if order_dates else None,
                            "end": order_dates[-1] if order_dates else None,
                        },
                        "confidence": round(min(0.95, 0.45 + 0.05 * active_days), 2),
                    },
                )
                db.add(entry)
                memory_count += 1

            # Store-level aggregate memory
            if by_product:
                total_store_revenue = sum(a["total_revenue"] for a in by_product.values())
                total_store_quantity = sum(a["total_quantity"] for a in by_product.values())
                all_dates = sorted({d for a in by_product.values() for d in a["order_dates"]})
                active_days = max(len(all_dates), 1)
                store_entry = GmMemory(
                    project_id=project.id,
                    memory_scope="shop",
                    source_type="shopify_sync",
                    memory_type="summary",
                    score_hint=round(total_store_revenue / active_days, 2),
                    content={
                        "source": "shopify_sync",
                        "scope": "shop",
                        "shop_id": workspace.id,
                        "shop_name": workspace.name,
                        "total_revenue": round(total_store_revenue, 2),
                        "total_quantity": total_store_quantity,
                        "daily_avg_revenue": round(total_store_revenue / active_days, 2),
                        "active_order_days": active_days,
                        "product_count": len(by_product),
                        "synced_at": _utcnow().isoformat(),
                        "summary": (
                            f"Store: ${total_store_revenue:.2f} total revenue, "
                            f"{total_store_quantity} units across {len(by_product)} products."
                        ),
                        "winning_patterns": [],
                        "avoid_patterns": [],
                        "evidence": [{"source": "shopify_sync", "sync_id": sync_record.id, "product_count": len(by_product)}],
                        "metric_window": {
                            "start": all_dates[0] if all_dates else None,
                            "end": all_dates[-1] if all_dates else None,
                        },
                        "confidence": round(min(0.95, 0.45 + 0.05 * active_days), 2),
                    },
                )
                db.add(store_entry)
                memory_count += 1

            items_synced = len(orders)

        sync_record.status = "completed"
        sync_record.items_synced = items_synced
        db.flush()
        return SyncResult(
            platform="shopify",
            sync_type=sync_type,
            status="completed",
            items_synced=items_synced,
            memory_entries_created=memory_count,
        )

    except Exception as exc:
        sync_record.status = "failed"
        sync_record.error_log = {"error": str(exc)}
        db.flush()
        logger.exception("Shopify sync failed")
        return SyncResult(
            platform="shopify",
            sync_type=sync_type,
            status="failed",
            items_synced=items_synced,
            memory_entries_created=memory_count,
            error=str(exc),
        )
    finally:
        await provider.close()


async def sync_meta(
    db: Session,
    *,
    workspace_name: str,
    project_name: str,
    sync_type: str = "performance",
    access_token: str = "",
    ad_account_id: str = "",
) -> SyncResult:
    import os
    from app.services.feedback import import_feedback_rows

    token = access_token or os.getenv("CRISPY_API_KEY_META", "")
    act_id = ad_account_id or os.getenv("CRISPY_API_KEY_META_ACCOUNT", "")
    if not token or not act_id:
        raise ValueError("Meta access_token and ad_account_id are required")

    workspace, project = _get_or_create_workspace_project(db, workspace_name, project_name)

    sync_record = IntegrationSync(
        workspace_id=workspace.id,
        project_id=project.id,
        platform="meta",
        sync_type=sync_type,
        status="running",
    )
    db.add(sync_record)
    db.flush()

    provider = MetaProvider(
        config={"access_token": token, "ad_account_id": act_id}
    )
    items_synced = 0
    memory_count = 0

    try:
        if sync_type in ("campaigns", "all"):
            campaigns = await provider.fetch_campaigns()
            for mc in campaigns:
                existing = db.scalar(
                    select(Campaign).where(
                        Campaign.project_id == project.id,
                        Campaign.platform_campaign_id == mc.campaign_id,
                    )
                )
                if existing:
                    existing.name = mc.name
                    existing.objective = mc.objective
                    existing.platform_ad_account_id = mc.ad_account_id
                    target = existing
                else:
                    target = Campaign(
                        project_id=project.id,
                        name=mc.name,
                        channel="meta",
                        objective=mc.objective,
                        platform_campaign_id=mc.campaign_id,
                        platform_ad_account_id=mc.ad_account_id,
                    )
                    db.add(target)

                # Auto-link campaign to product by name matching
                if not target.product_id:
                    products = db.scalars(
                        select(Product).where(Product.project_id == project.id)
                    ).all()
                    camp_lower = target.name.lower()
                    for prod in products:
                        prod_code_lower = (prod.product_code or "").lower()
                        prod_name_lower = (prod.name or "").lower()
                        if (prod_code_lower and prod_code_lower in camp_lower) or \
                           (prod_name_lower and (prod_name_lower in camp_lower or camp_lower in prod_name_lower)):
                            target.product_id = prod.id
                            break

                items_synced += 1

        if sync_type in ("performance", "all"):
            rows = await provider.fetch_ad_performance()
            feedback_rows: list[FeedbackRow] = []
            for ir in rows:
                campaign = db.scalar(
                    select(Campaign).where(
                        Campaign.project_id == project.id,
                        Campaign.platform_campaign_id == ir.ad_id,
                    )
                )
                campaign = campaign or db.scalar(
                    select(Campaign).where(
                        Campaign.project_id == project.id,
                        Campaign.name == ir.ad_name,
                    )
                )

                # Resolve product_code through campaign → product chain
                product_code = ""
                if campaign and campaign.product_id:
                    product = db.get(Product, campaign.product_id)
                    if product:
                        product_code = product.product_code

                feedback_rows.append(FeedbackRow(
                    project_name=project_name,
                    creative_key=ir.creative_id or ir.ad_id,
                    variant_id=None,
                    campaign_name=ir.ad_name,
                    run_id=None,
                    impressions=ir.impressions,
                    clicks=ir.clicks,
                    spend=ir.spend,
                    conversions=ir.conversions,
                    revenue=ir.revenue,
                    period_start=date.fromisoformat(ir.date_start) if ir.date_start else None,
                    period_end=date.fromisoformat(ir.date_stop) if ir.date_stop else None,
                    platform="meta",
                    platform_campaign_id=(
                        campaign.platform_campaign_id if campaign else None
                    ),
                    product_code=product_code or None,
                    industry_code=workspace.industry_code or None,
                ))

            if feedback_rows:
                import_record, snapshot_count, memory = import_feedback_rows(
                    db,
                    workspace_name=workspace_name,
                    project_name=project_name,
                    rows=feedback_rows,
                    file_name=f"meta_sync_{_utcnow().strftime('%Y%m%d_%H%M%S')}",
                )
                items_synced = snapshot_count
                memory_count = 1 if memory else 0

                # Store-level aggregate memory from Meta ad performance
                total_spend = sum(r.spend for r in feedback_rows)
                total_revenue = sum(r.revenue for r in feedback_rows)
                total_impressions = sum(r.impressions for r in feedback_rows)
                total_clicks = sum(r.clicks for r in feedback_rows)
                total_conversions = sum(r.conversions for r in feedback_rows)
                starts = [r.period_start.isoformat() for r in feedback_rows if r.period_start]
                ends = [r.period_end.isoformat() for r in feedback_rows if r.period_end]
                if total_impressions > 0:
                    store_entry = GmMemory(
                        project_id=project.id,
                        memory_scope="shop",
                        source_type="meta_sync",
                        memory_type="summary",
                        score_hint=round(total_revenue / total_spend, 4) if total_spend > 0 else 0,
                        content={
                            "source": "meta_sync",
                            "scope": "shop",
                            "shop_id": workspace.id,
                            "shop_name": workspace.name,
                            "total_spend": round(total_spend, 2),
                            "total_revenue": round(total_revenue, 2),
                            "total_impressions": total_impressions,
                            "total_clicks": total_clicks,
                            "total_conversions": total_conversions,
                            "overall_roas": round(total_revenue / total_spend, 4) if total_spend > 0 else 0,
                            "overall_ctr": round(total_clicks / total_impressions * 100, 4) if total_impressions > 0 else 0,
                            "creative_count": len({r.creative_key for r in feedback_rows}),
                            "synced_at": _utcnow().isoformat(),
                            "summary": (
                                f"Meta ad account: ${total_spend:.2f} spend, "
                                f"${total_revenue:.2f} revenue, "
                                f"ROAS {total_revenue/total_spend:.2f}" if total_spend > 0 else "No spend data"
                            ),
                            "winning_patterns": [],
                            "avoid_patterns": [],
                            "evidence": [{"source": "meta_sync", "sync_id": sync_record.id, "creative_count": len({r.creative_key for r in feedback_rows})}],
                            "metric_window": {
                                "start": min(starts) if starts else None,
                                "end": max(ends) if ends else None,
                            },
                            "confidence": round(min(0.95, 0.45 + 0.03 * len(feedback_rows)), 2),
                        },
                    )
                    db.add(store_entry)
                    memory_count += 1
            else:
                items_synced = 0

        sync_record.status = "completed"
        sync_record.items_synced = items_synced
        db.flush()
        return SyncResult(
            platform="meta",
            sync_type=sync_type,
            status="completed",
            items_synced=items_synced,
            memory_entries_created=memory_count,
        )

    except Exception as exc:
        sync_record.status = "failed"
        sync_record.error_log = {"error": str(exc)}
        db.flush()
        logger.exception("Meta sync failed")
        return SyncResult(
            platform="meta",
            sync_type=sync_type,
            status="failed",
            items_synced=items_synced,
            memory_entries_created=memory_count,
            error=str(exc),
        )
    finally:
        await provider.close()

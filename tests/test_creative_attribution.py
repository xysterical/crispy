from __future__ import annotations

import io

from sqlalchemy import select

from app.data.models import (
    Campaign,
    GmMemory,
    PerformanceSnapshot,
    PipelineRun,
    Product,
    Project,
    RunVariant,
    VariantAsset,
    Workspace,
)
from app.schemas.contracts import FeedbackRow
from app.analytics.creative_decisions import CreativeDecisionAnalyzer, refresh_creative_decision_memory
from app.services.creative_attribution import canonical_creative_key, parse_creative_key, resolve_performance_attribution
from app.services.feedback import import_feedback_rows


def _seed_run(db_session, *, variant_count: int = 1):
    workspace = Workspace(name="w-attr", industry_code="pet_care")
    db_session.add(workspace)
    db_session.flush()
    project = Project(workspace_id=workspace.id, name="p-attr")
    db_session.add(project)
    db_session.flush()
    product = Product(project_id=project.id, name="Pet Brush", product_code="ATTR-001")
    db_session.add(product)
    db_session.flush()
    campaign = Campaign(
        project_id=project.id,
        product_id=product.id,
        name="ATTR Meta Campaign",
        platform_campaign_id="camp-1",
    )
    db_session.add(campaign)
    db_session.flush()
    run = PipelineRun(
        workspace_id=workspace.id,
        project_id=project.id,
        product_id=product.id,
        campaign_id=campaign.id,
        product_code=product.product_code,
        industry_code=workspace.industry_code,
    )
    db_session.add(run)
    db_session.flush()
    variants = []
    for idx in range(variant_count):
        variant_id = f"V{idx + 1}"
        variant = RunVariant(
            run_id=run.id,
            variant_id=variant_id,
            angle=f"Angle {variant_id}",
            hook=f"Hook {variant_id}",
            message=f"Message {variant_id}",
        )
        db_session.add(variant)
        db_session.flush()
        asset = VariantAsset(
            run_variant_id=variant.id,
            run_id=run.id,
            stage_name="copy_image_generation",
            asset_type="image",
            uri=f"/tmp/{variant_id}.png",
            idempotency_key=f"image-{variant_id}",
            payload={"external_creative_id": f"meta-{variant_id}"},
        )
        db_session.add(asset)
        variants.append(variant)
    db_session.flush()
    return workspace, project, product, campaign, run, variants


def test_canonical_creative_key_round_trips():
    key = canonical_creative_key("run-1", "V1", "image")
    assert key == "crispy:run-1:V1:image"
    parsed = parse_creative_key(key)
    assert parsed is not None
    assert parsed.run_id == "run-1"
    assert parsed.variant_id == "V1"
    assert parsed.asset_type == "image"
    assert parse_creative_key("V1") is None


def test_resolver_matches_canonical_run_variant_and_platform_id(db_session):
    _, project, _, _, run, variants = _seed_run(db_session)
    canonical = canonical_creative_key(run.id, "V1", "image")

    exact = resolve_performance_attribution(
        db_session,
        project_id=project.id,
        creative_key=canonical,
    )
    assert exact.status == "attributed"
    assert exact.method == "canonical_creative_key"
    assert exact.strategy_safe
    assert exact.run_variant_id == variants[0].id

    legacy = resolve_performance_attribution(
        db_session,
        project_id=project.id,
        creative_key="V1",
        run_id=run.id,
        variant_id="V1",
    )
    assert legacy.status == "attributed"
    assert legacy.method == "run_variant"
    assert legacy.creative_key == canonical

    platform = resolve_performance_attribution(
        db_session,
        project_id=project.id,
        creative_key="meta-V1",
        platform_creative_id="meta-V1",
        asset_type="image",
    )
    assert platform.status == "attributed"
    assert platform.method == "platform_external_id"
    assert platform.run_variant_id == variants[0].id


def test_feedback_import_records_attribution_and_blocks_fallback_memory(db_session):
    _, project, product, campaign, run, _ = _seed_run(db_session, variant_count=2)

    _, snapshot_count, memory = import_feedback_rows(
        db_session,
        workspace_name="w-attr",
        project_name="p-attr",
        file_name="weekly.csv",
        rows=[
            FeedbackRow(
                project_name="p-attr",
                creative_key="V1",
                variant_id="V1",
                run_id=run.id,
                asset_type="image",
                impressions=1200,
                clicks=42,
                spend=40,
                conversions=6,
                revenue=130,
            ),
            FeedbackRow(
                project_name="p-attr",
                creative_key="unknown",
                campaign_name=campaign.name,
                platform_campaign_id=campaign.platform_campaign_id,
                product_code=product.product_code,
                impressions=1300,
                clicks=30,
                spend=35,
                conversions=2,
                revenue=60,
            ),
        ],
    )

    assert snapshot_count == 2
    assert memory is not None

    snapshots = db_session.scalars(
        select(PerformanceSnapshot).where(PerformanceSnapshot.project_id == project.id)
    ).all()
    safe = [s for s in snapshots if (s.metrics or {}).get("attribution", {}).get("strategy_safe")]
    blocked = [s for s in snapshots if not (s.metrics or {}).get("attribution", {}).get("strategy_safe")]
    assert len(safe) == 1
    assert safe[0].creative_key == canonical_creative_key(run.id, "V1", "image")
    assert blocked[0].metrics["attribution"]["status"] == "ambiguous"

    memories = db_session.scalars(
        select(GmMemory).where(GmMemory.project_id == project.id, GmMemory.memory_scope == "product")
    ).all()
    assert len(memories) == 1
    content = memories[0].content or {}
    all_memory_keys = [item["variant_id"] for item in content.get("top_variants", [])]
    assert all_memory_keys == [canonical_creative_key(run.id, "V1", "image")]


def test_creative_decision_analyzer_classifies_direction_and_refreshes_memory(db_session):
    _, project, _, _, run, variants = _seed_run(db_session, variant_count=4)
    v3_asset = db_session.scalar(
        select(VariantAsset).where(VariantAsset.run_variant_id == variants[2].id)
    )
    v3_asset.payload = {
        **(v3_asset.payload or {}),
        "visual_qa": {"status": "fail", "flags": ["visual_qa_placeholder"]},
    }

    rows = [
        FeedbackRow(
            project_name="p-attr",
            creative_key="V1",
            variant_id="V1",
            run_id=run.id,
            asset_type="image",
            impressions=2000,
            clicks=100,
            spend=40,
            conversions=20,
            revenue=400,
        ),
        FeedbackRow(
            project_name="p-attr",
            creative_key="V2",
            variant_id="V2",
            run_id=run.id,
            asset_type="image",
            impressions=2000,
            clicks=20,
            spend=80,
            conversions=1,
            revenue=20,
        ),
        FeedbackRow(
            project_name="p-attr",
            creative_key="V3",
            variant_id="V3",
            run_id=run.id,
            asset_type="image",
            impressions=2000,
            clicks=100,
            spend=40,
            conversions=20,
            revenue=400,
        ),
        FeedbackRow(
            project_name="p-attr",
            creative_key="V4",
            variant_id="V4",
            run_id=run.id,
            asset_type="image",
            impressions=2000,
            clicks=100,
            spend=40,
            conversions=1,
            revenue=20,
        ),
    ]
    import_feedback_rows(
        db_session,
        workspace_name="w-attr",
        project_name="p-attr",
        file_name="creative_decisions.csv",
        rows=rows,
    )

    report = CreativeDecisionAnalyzer(db_session, project.id).decision_report()
    promote_keys = {item["creative_key"] for item in report["promote"]}
    retire_keys = {item["creative_key"] for item in report["retire"]}
    needs_test = {item["creative_key"]: item for item in report["needs_test"]}

    assert canonical_creative_key(run.id, "V1", "image") in promote_keys
    assert canonical_creative_key(run.id, "V2", "image") in retire_keys
    assert "production_quality_blocked" in needs_test[canonical_creative_key(run.id, "V3", "image")]["reasons"]
    assert "high_attention_low_intent" in needs_test[canonical_creative_key(run.id, "V4", "image")]["reasons"]
    assert report["attribution_summary"]["strategy_safe_rate"] == 1.0
    assert report["next_generation"]["priority_seeds"][0]["angle"] == "Angle V1"
    assert report["next_generation"]["avoid_seeds"][0]["hook"] == "Hook V2"
    assert report["next_generation"]["test_queue"]
    assert report["next_generation"]["dimension_priorities"]["angles"][0]["value"] == "Angle V1"

    _, memories = refresh_creative_decision_memory(db_session, project_id=project.id)
    assert len(memories) == 1
    memory = memories[0]
    assert memory.source_type == "creative_decision_attribution"
    content = memory.content or {}
    assert len(content["winning_patterns"]) == 1
    assert len(content["avoid_patterns"]) == 1
    assert content["winning_patterns"][0]["decision"] == "promote"
    assert content["avoid_patterns"][0]["decision"] == "retire"
    assert content["next_generation"]["priority_seeds"][0]["creative_key"] == canonical_creative_key(run.id, "V1", "image")
    assert content["attribution_summary"]["creative_count"] == 4


def test_creative_decision_dashboard_api_and_planning_insight(client, db_session):
    _, project, _, _, run, _ = _seed_run(db_session, variant_count=2)
    import_feedback_rows(
        db_session,
        workspace_name="w-attr",
        project_name="p-attr",
        file_name="api_decisions.csv",
        rows=[
            FeedbackRow(
                project_name="p-attr",
                creative_key="V1",
                variant_id="V1",
                run_id=run.id,
                asset_type="image",
                impressions=2000,
                clicks=100,
                spend=40,
                conversions=20,
                revenue=400,
            ),
            FeedbackRow(
                project_name="p-attr",
                creative_key="V2",
                variant_id="V2",
                run_id=run.id,
                asset_type="image",
                impressions=2000,
                clicks=20,
                spend=80,
                conversions=1,
                revenue=20,
            ),
            FeedbackRow(
                project_name="p-attr",
                creative_key="unmatched",
                impressions=2000,
                clicks=50,
                spend=50,
                conversions=5,
                revenue=100,
            ),
        ],
    )
    db_session.commit()

    resp = client.get(
        "/data-dashboard/creative-decisions",
        params={"workspace_name": "w-attr", "project_name": "p-attr"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert canonical_creative_key(run.id, "V1", "image") in {item["creative_key"] for item in payload["promote"]}
    assert canonical_creative_key(run.id, "V2", "image") in {item["creative_key"] for item in payload["retire"]}
    assert payload["unmatched"][0]["status"] == "unmatched"
    assert payload["attribution_summary"]["unmatched_snapshots"] == 1
    assert payload["next_generation"]["attribution_quality"]["recommendation"] == "improve_tracking"
    assert payload["next_generation"]["priority_seeds"]

    refresh_resp = client.post(
        "/data-dashboard/creative-decisions/refresh",
        params={"workspace_name": "w-attr", "project_name": "p-attr"},
    )
    assert refresh_resp.status_code == 200
    assert refresh_resp.json()["memories_created"] == 1

    from app.services.runs import _analytics_insights

    insights = _analytics_insights(db_session, run)
    decision = [item for item in insights if item["source_type"] == "creative_decision_attribution"][0]
    content = decision["content"]
    assert content["promote"]
    assert content["retire"]
    assert content["next_generation"]["priority_seeds"]
    assert content["attribution_summary"]["unmatched_snapshots"] == 1
    assert "unmatched" not in content
    assert content["unmatched_count"] == 1


def test_offline_store_csv_import_simulates_shop_data_and_creative_metrics(client, db_session):
    _, _, _, _, run, _ = _seed_run(db_session, variant_count=2)
    db_session.commit()
    shopify_csv = (
        "product_code,product_name,date,total_revenue,total_quantity\n"
        "ATTR-001,Pet Brush,2026-07-01,120,4\n"
        "ATTR-001,Pet Brush,2026-07-02,80,2\n"
    ).encode("utf-8")

    shopify_resp = client.post(
        "/data-dashboard/offline-csv-import/shopify",
        data={"workspace_name": "w-attr", "project_name": "p-attr"},
        files={"file": ("shopify.csv", io.BytesIO(shopify_csv), "text/csv")},
    )
    assert shopify_resp.status_code == 200
    payload = shopify_resp.json()
    assert payload["platform"] == "shopify"
    assert payload["rows"] == 2
    assert payload["products_seen"] == 2
    assert payload["product_memory_count"] == 1
    assert payload["shop_memory_count"] == 1
    assert payload["snapshots_created"] == 0

    meta_csv = (
        "creative_key,variant_id,run_id,asset_type,impressions,clicks,spend,conversions,attributed_revenue,product_code\n"
        f"V1,V1,{run.id},image,2000,100,40,20,400,ATTR-001\n"
        f"V2,V2,{run.id},image,2000,20,80,1,20,ATTR-001\n"
    ).encode("utf-8")
    meta_resp = client.post(
        "/data-dashboard/offline-csv-import/meta",
        data={"workspace_name": "w-attr", "project_name": "p-attr"},
        files={"file": ("meta.csv", io.BytesIO(meta_csv), "text/csv")},
    )
    assert meta_resp.status_code == 200
    payload = meta_resp.json()
    assert payload["platform"] == "meta"
    assert payload["snapshots_created"] == 2

    batches = client.get(
        "/data-dashboard/offline-csv-imports",
        params={"workspace_name": "w-attr", "project_name": "p-attr"},
    )
    assert batches.status_code == 200
    batch_items = batches.json()["items"]
    assert {item["platform"] for item in batch_items} == {"shopify", "meta"}
    assert {item["file_name"] for item in batch_items} == {"shopify.csv", "meta.csv"}
    assert all(item["file_size_bytes"] > 0 for item in batch_items)

    summary = client.get(
        "/data-dashboard/summary",
        params={"workspace_name": "w-attr", "project_name": "p-attr"},
    )
    assert summary.status_code == 200
    assert summary.json()["store_data_source"] == "offline_csv_import"
    assert summary.json()["shopify_revenue"] == 200

    store = client.get(
        "/data-dashboard/store-analytics",
        params={"workspace_name": "w-attr", "project_name": "p-attr"},
    )
    assert store.status_code == 200
    assert store.json()["products"][0]["product_code"] == "ATTR-001"
    assert store.json()["products"][0]["revenue"] == 200

    decisions = client.get(
        "/data-dashboard/creative-decisions",
        params={"workspace_name": "w-attr", "project_name": "p-attr"},
    )
    assert decisions.status_code == 200
    assert decisions.json()["promote"]
    assert decisions.json()["retire"]

    delete_resp = client.delete(
        f"/data-dashboard/offline-csv-imports/{payload['batch_id']}",
        params={"workspace_name": "w-attr", "project_name": "p-attr"},
    )
    assert delete_resp.status_code == 200
    assert delete_resp.json()["snapshots_deleted"] == 2


def test_offline_store_csv_without_metrics_does_not_write_memory(client, db_session):
    workspace = Workspace(name="w-empty", industry_code="pet_care")
    db_session.add(workspace)
    db_session.flush()
    db_session.add(Project(workspace_id=workspace.id, name="p-empty"))
    db_session.commit()

    csv_content = "product_code,product_name\nEMPTY-1,Empty Product\n".encode("utf-8")
    resp = client.post(
        "/data-dashboard/offline-csv-import/shopify",
        data={"workspace_name": "w-empty", "project_name": "p-empty"},
        files={"file": ("empty.csv", io.BytesIO(csv_content), "text/csv")},
    )
    assert resp.status_code == 400
    assert "requires revenue or quantity" in resp.text

    memories = db_session.scalars(select(GmMemory).where(GmMemory.source_type == "offline_csv_import")).all()
    assert memories == []

from __future__ import annotations

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

    _, memories = refresh_creative_decision_memory(db_session, project_id=project.id)
    assert len(memories) == 1
    memory = memories[0]
    assert memory.source_type == "creative_decision_attribution"
    content = memory.content or {}
    assert len(content["winning_patterns"]) == 1
    assert len(content["avoid_patterns"]) == 1
    assert content["winning_patterns"][0]["decision"] == "promote"
    assert content["avoid_patterns"][0]["decision"] == "retire"

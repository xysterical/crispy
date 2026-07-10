from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.data.models import Campaign, PipelineRun, Product, RunVariant, VariantAsset


CANONICAL_PREFIX = "crispy"
DEFAULT_CREATIVE_ASSET_TYPE = "creative"


@dataclass(frozen=True)
class ParsedCreativeKey:
    run_id: str
    variant_id: str
    asset_type: str


@dataclass
class AttributionResult:
    status: str
    method: str
    confidence: float
    creative_key: str
    run_id: str | None = None
    run_variant_id: str | None = None
    variant_id: str | None = None
    variant_asset_id: str | None = None
    asset_type: str | None = None
    warnings: list[str] = field(default_factory=list)
    run_variant: RunVariant | None = None
    variant_asset: VariantAsset | None = None

    @property
    def strategy_safe(self) -> bool:
        return self.status == "attributed" and self.confidence >= 0.75

    def metadata(self) -> dict:
        return {
            "status": self.status,
            "method": self.method,
            "confidence": self.confidence,
            "run_id": self.run_id,
            "run_variant_id": self.run_variant_id,
            "variant_id": self.variant_id,
            "variant_asset_id": self.variant_asset_id,
            "asset_type": self.asset_type,
            "warnings": self.warnings,
            "strategy_safe": self.strategy_safe,
        }


def canonical_creative_key(run_id: str, variant_id: str, asset_type: str | None = None) -> str:
    return f"{CANONICAL_PREFIX}:{run_id}:{variant_id}:{asset_type or DEFAULT_CREATIVE_ASSET_TYPE}"


def parse_creative_key(value: str | None) -> ParsedCreativeKey | None:
    if not value:
        return None
    parts = value.split(":")
    if len(parts) != 4 or parts[0] != CANONICAL_PREFIX:
        return None
    _, run_id, variant_id, asset_type = parts
    if not run_id or not variant_id or not asset_type:
        return None
    return ParsedCreativeKey(run_id=run_id, variant_id=variant_id, asset_type=asset_type)


def _latest_asset(db: Session, run_variant_id: str, asset_type: str | None) -> VariantAsset | None:
    query = select(VariantAsset).where(VariantAsset.run_variant_id == run_variant_id)
    if asset_type and asset_type != DEFAULT_CREATIVE_ASSET_TYPE:
        query = query.where(VariantAsset.asset_type == asset_type)
    return db.scalar(query.order_by(desc(VariantAsset.created_at)).limit(1))


def _result_from_variant(
    db: Session,
    *,
    status: str,
    method: str,
    confidence: float,
    variant: RunVariant,
    asset_type: str | None,
    warnings: list[str] | None = None,
) -> AttributionResult:
    asset = _latest_asset(db, variant.id, asset_type)
    resolved_asset_type = asset_type or (asset.asset_type if asset else DEFAULT_CREATIVE_ASSET_TYPE)
    key = canonical_creative_key(variant.run_id, variant.variant_id, resolved_asset_type)
    return AttributionResult(
        status=status,
        method=method,
        confidence=confidence,
        creative_key=key,
        run_id=variant.run_id,
        run_variant_id=variant.id,
        variant_id=variant.variant_id,
        variant_asset_id=asset.id if asset else None,
        asset_type=resolved_asset_type,
        warnings=warnings or [],
        run_variant=variant,
        variant_asset=asset,
    )


def _find_variant(db: Session, run_id: str | None, variant_id: str | None) -> RunVariant | None:
    if not run_id or not variant_id:
        return None
    return db.scalar(
        select(RunVariant).where(
            RunVariant.run_id == run_id,
            RunVariant.variant_id == variant_id,
        )
    )


def _payload_contains_external_id(payload: dict, external_id: str) -> bool:
    keys = {
        "creative_key",
        "canonical_creative_key",
        "platform_creative_id",
        "platform_ad_id",
        "external_creative_id",
        "external_ad_id",
        "ad_id",
        "creative_id",
    }
    for key in keys:
        if str(payload.get(key) or "") == external_id:
            return True
    platform_ids = payload.get("platform_ids")
    if isinstance(platform_ids, list) and external_id in {str(item) for item in platform_ids}:
        return True
    return False


def _find_variant_by_platform_id(
    db: Session,
    *,
    project_id: str,
    external_ids: list[str],
    asset_type: str | None,
) -> RunVariant | None:
    ids = [item for item in external_ids if item]
    if not ids:
        return None
    assets = db.scalars(
        select(VariantAsset)
        .join(PipelineRun, VariantAsset.run_id == PipelineRun.id)
        .where(PipelineRun.project_id == project_id)
        .order_by(desc(VariantAsset.created_at))
        .limit(500)
    ).all()
    matched_variant_ids: set[str] = set()
    for asset in assets:
        if asset_type and asset.asset_type != asset_type:
            continue
        payload = asset.payload or {}
        if any(_payload_contains_external_id(payload, external_id) for external_id in ids):
            matched_variant_ids.add(asset.run_variant_id)
    if len(matched_variant_ids) != 1:
        return None
    return db.get(RunVariant, next(iter(matched_variant_ids)))


def _fallback_variants(
    db: Session,
    *,
    project_id: str,
    campaign_id: str | None,
    product_code: str | None,
    limit: int = 20,
) -> list[RunVariant]:
    query = (
        select(RunVariant)
        .join(PipelineRun, RunVariant.run_id == PipelineRun.id)
        .where(PipelineRun.project_id == project_id)
    )
    if campaign_id:
        query = query.where(PipelineRun.campaign_id == campaign_id)
    if product_code:
        query = query.where(PipelineRun.product_code == product_code)
    return db.scalars(query.order_by(desc(RunVariant.created_at)).limit(limit)).all()


def resolve_performance_attribution(
    db: Session,
    *,
    project_id: str,
    creative_key: str | None,
    run_id: str | None = None,
    variant_id: str | None = None,
    asset_type: str | None = None,
    platform_ad_id: str | None = None,
    platform_creative_id: str | None = None,
    campaign_id: str | None = None,
    product_code: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
) -> AttributionResult:
    parsed = parse_creative_key(creative_key)
    if parsed:
        variant = _find_variant(db, parsed.run_id, parsed.variant_id)
        if variant:
            return _result_from_variant(
                db,
                status="attributed",
                method="canonical_creative_key",
                confidence=1.0,
                variant=variant,
                asset_type=parsed.asset_type,
            )
        return AttributionResult(
            status="unmatched",
            method="canonical_creative_key",
            confidence=0.0,
            creative_key=creative_key or "",
            run_id=parsed.run_id,
            variant_id=parsed.variant_id,
            asset_type=parsed.asset_type,
            warnings=["canonical key did not match a run variant"],
        )

    variant = _find_variant(db, run_id, variant_id or creative_key)
    if variant:
        return _result_from_variant(
            db,
            status="attributed",
            method="run_variant",
            confidence=0.95,
            variant=variant,
            asset_type=asset_type,
        )

    platform_variant = _find_variant_by_platform_id(
        db,
        project_id=project_id,
        external_ids=[platform_creative_id or "", platform_ad_id or "", creative_key or ""],
        asset_type=asset_type,
    )
    if platform_variant:
        return _result_from_variant(
            db,
            status="attributed",
            method="platform_external_id",
            confidence=0.85,
            variant=platform_variant,
            asset_type=asset_type,
        )

    if campaign_id and product_code:
        candidates = _fallback_variants(
            db,
            project_id=project_id,
            campaign_id=campaign_id,
            product_code=product_code,
        )
        if len(candidates) == 1:
            return _result_from_variant(
                db,
                status="fallback",
                method="campaign_product",
                confidence=0.45,
                variant=candidates[0],
                asset_type=asset_type,
                warnings=["fallback attribution is not strategy safe"],
            )
        if len(candidates) > 1:
            return AttributionResult(
                status="ambiguous",
                method="campaign_product",
                confidence=0.0,
                creative_key=creative_key or "",
                asset_type=asset_type,
                warnings=[f"{len(candidates)} variants match campaign and product"],
            )

    if product_code:
        candidates = _fallback_variants(
            db,
            project_id=project_id,
            campaign_id=None,
            product_code=product_code,
        )
        if len(candidates) == 1:
            warnings = ["product/date fallback attribution is not strategy safe"]
            if period_start or period_end:
                warnings.append("date window used only as supporting context")
            return _result_from_variant(
                db,
                status="fallback",
                method="product_date",
                confidence=0.3,
                variant=candidates[0],
                asset_type=asset_type,
                warnings=warnings,
            )
        if len(candidates) > 1:
            return AttributionResult(
                status="ambiguous",
                method="product_date",
                confidence=0.0,
                creative_key=creative_key or "",
                asset_type=asset_type,
                warnings=[f"{len(candidates)} variants match product fallback"],
            )

    return AttributionResult(
        status="unmatched",
        method="unmatched",
        confidence=0.0,
        creative_key=creative_key or "",
        asset_type=asset_type,
        warnings=["no deterministic attribution match"],
    )


def resolve_campaign_id(
    db: Session,
    *,
    project_id: str,
    campaign_name: str | None,
    platform_campaign_id: str | None,
) -> str | None:
    if platform_campaign_id:
        campaign = db.scalar(
            select(Campaign).where(
                Campaign.project_id == project_id,
                Campaign.platform_campaign_id == platform_campaign_id,
            )
        )
        if campaign:
            return campaign.id
    if campaign_name:
        campaign = db.scalar(
            select(Campaign).where(
                Campaign.project_id == project_id,
                Campaign.name == campaign_name,
            )
        )
        if campaign:
            return campaign.id
    return None


def product_code_from_campaign(db: Session, campaign_id: str | None) -> str | None:
    if not campaign_id:
        return None
    campaign = db.get(Campaign, campaign_id)
    if not campaign or not campaign.product_id:
        return None
    product = db.get(Product, campaign.product_id)
    return product.product_code if product else None

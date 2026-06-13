from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

from sqlalchemy.orm import Session

from app.data.models import Campaign, PipelineRun, RunVariant, VariantAsset


def _file_to_data_url(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def build_reference_bundle(
    db: Session,
    *,
    product_code: str,
    channel: str,
    limit_images: int = 2,
    limit_frames: int = 2,
) -> dict:
    query = (
        db.query(VariantAsset, RunVariant.current_score, Campaign.channel)
        .join(RunVariant, VariantAsset.run_variant_id == RunVariant.id)
        .join(PipelineRun, VariantAsset.run_id == PipelineRun.id)
        .join(Campaign, PipelineRun.campaign_id == Campaign.id)
        .filter(
            PipelineRun.product_code == product_code,
            VariantAsset.asset_type.in_(["image", "storyboard_frame"]),
            VariantAsset.uri.isnot(None),
            RunVariant.current_score.isnot(None),
        )
        .order_by(RunVariant.current_score.desc())
    )
    if channel:
        query = query.filter(Campaign.channel == channel)
    rows = query.limit(40).all()

    images: list[dict] = []
    frames: list[dict] = []
    for asset, score, asset_channel in rows:
        data_url = _file_to_data_url(Path(asset.uri))
        if not data_url:
            continue
        item = {
            "uri": data_url,
            "asset_type": asset.asset_type,
            "score": score,
            "source_type": f"historical_{asset.asset_type}",
            "channel": asset_channel,
        }
        if asset.asset_type == "image" and len(images) < limit_images:
            images.append(item)
        elif asset.asset_type == "storyboard_frame" and len(frames) < limit_frames:
            frames.append(item)
        if len(images) >= limit_images and len(frames) >= limit_frames:
            break

    return {"images": images, "frames": frames}

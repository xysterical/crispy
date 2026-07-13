from __future__ import annotations

from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.data.models import GmMemory, Project, Workspace
from app.services.gm_memory import memory_dirty_reasons, memory_is_strategy_safe
from app.services.shop_analysis import RESEARCH_SOURCE_TYPES


MEMORY_SELECTION_MODES = {"auto", "manual", "none"}
SHOP_MEMORY_SOURCES = [*RESEARCH_SOURCE_TYPES, "shopify_sync", "meta_sync"]


def normalize_memory_selection(raw: Any) -> dict:
    if not isinstance(raw, dict):
        raw = {}
    mode = str(raw.get("mode") or "auto").strip().lower()
    if mode not in MEMORY_SELECTION_MODES:
        mode = "auto"
    return {
        "mode": mode,
        "include_ids": _string_list(raw.get("include_ids")),
        "exclude_ids": _string_list(raw.get("exclude_ids")),
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    results: list[str] = []
    for item in value:
        item_id = str(item or "").strip()
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        results.append(item_id)
    return results


def build_run_memory_candidates(
    db: Session,
    *,
    workspace_name: str,
    project_name: str | None = None,
    product_code: str | None = None,
    industry_code: str | None = None,
    limit: int = 80,
) -> dict:
    workspace = db.scalar(select(Workspace).where(Workspace.name == workspace_name)) if workspace_name else None
    project = None
    if workspace and project_name:
        project = db.scalar(
            select(Project).where(Project.workspace_id == workspace.id, Project.name == project_name)
        )

    product_rows: list[GmMemory] = []
    industry_rows: list[GmMemory] = []
    if project:
        if product_code:
            product_rows = list(db.scalars(
                select(GmMemory)
                .where(
                    GmMemory.project_id == project.id,
                    GmMemory.memory_scope == "product",
                    GmMemory.product_code == product_code,
                    GmMemory.status == "active",
                )
                .order_by(desc(GmMemory.score_hint), desc(GmMemory.created_at))
                .limit(20)
            ).all())
        if industry_code:
            industry_rows = list(db.scalars(
                select(GmMemory)
                .where(
                    GmMemory.project_id == project.id,
                    GmMemory.memory_scope == "industry",
                    GmMemory.industry_code == industry_code,
                    GmMemory.status == "active",
                )
                .order_by(desc(GmMemory.score_hint), desc(GmMemory.created_at))
                .limit(20)
            ).all())

    shop_rows: list[GmMemory] = []
    if workspace:
        shop_candidates = db.scalars(
            select(GmMemory)
            .where(
                GmMemory.memory_scope == "shop",
                GmMemory.source_type.in_(SHOP_MEMORY_SOURCES),
                GmMemory.status == "active",
            )
            .order_by(desc(GmMemory.score_hint), desc(GmMemory.created_at))
            .limit(50)
        ).all()
        shop_rows = [
            row for row in shop_candidates
            if (row.content or {}).get("shop_id") == workspace.id
        ][:5]

    product_rows = sorted(product_rows, key=_gm_memory_priority)[:10]
    industry_rows = sorted(industry_rows, key=_gm_memory_priority)[:10]
    shop_rows = sorted(shop_rows, key=_gm_memory_priority)[:5]
    default_ids = {
        row.id
        for row in [*product_rows[:3], *shop_rows[:3], *industry_rows[:2]]
        if memory_is_strategy_safe(row)
    }
    rows = _dedupe_rows([*product_rows, *shop_rows, *industry_rows])[:limit]
    items = [_candidate_item(row, selected_by_default=row.id in default_ids) for row in rows]
    return {
        "workspace_name": workspace_name,
        "workspace_id": workspace.id if workspace else None,
        "project_name": project_name,
        "project_id": project.id if project else None,
        "product_code": product_code or "",
        "industry_code": industry_code or "",
        "summary": {
            "candidate_count": len(items),
            "safe_count": sum(1 for item in items if item["strategy_safe"]),
            "default_selected_count": sum(1 for item in items if item["selected_by_default"]),
        },
        "items": items,
    }


def _dedupe_rows(rows: list[GmMemory]) -> list[GmMemory]:
    seen: set[str] = set()
    results: list[GmMemory] = []
    for row in rows:
        if row.id in seen:
            continue
        seen.add(row.id)
        results.append(row)
    return results


def _candidate_item(row: GmMemory, *, selected_by_default: bool) -> dict:
    content = row.content or {}
    dirty_reasons = memory_dirty_reasons(row)
    return {
        "id": row.id,
        "memory_scope": row.memory_scope,
        "product_code": row.product_code,
        "industry_code": row.industry_code,
        "source_type": row.source_type,
        "memory_type": row.memory_type,
        "status": row.status,
        "pinned": bool(row.pinned),
        "score_hint": row.score_hint,
        "summary": _memory_summary(content),
        "dirty_reasons": dirty_reasons,
        "strategy_safe": not dirty_reasons,
        "selected_by_default": selected_by_default,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "content": content,
    }


def _memory_summary(content: dict) -> str:
    value = (
        content.get("summary")
        or content.get("report")
        or content.get("profile", {}).get("positioning")
        or content.get("findings")
        or content.get("strategic_implications")
        or ""
    )
    if isinstance(value, dict | list):
        value = str(value)
    return str(value or "").strip()[:240]


def _gm_memory_priority(row: GmMemory) -> tuple[int, int, float, float]:
    return (
        0 if row.memory_type == "summary" else 1,
        -int(bool(row.pinned)),
        -(row.score_hint or 0),
        -(row.created_at.timestamp() if row.created_at else 0),
    )

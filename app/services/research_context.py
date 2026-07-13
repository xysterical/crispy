from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.data.models import GmMemory, Project, Workspace
from app.services.gm_memory import memory_dirty_reasons, memory_is_strategy_safe
from app.services.memory_selection import normalize_memory_selection
from app.services.shop_analysis import RESEARCH_SOURCE_TYPES, research_refresh_state


RESEARCH_TYPE_TOOL_NEEDS = {
    "shop_profile": ["LLM", "Firecrawl", "Tavily"],
    "competitor_analysis": ["LLM", "Tavily", "Firecrawl"],
    "industry_baseline": ["LLM", "Tavily"],
    "audience_pain_points": ["LLM", "Tavily", "Firecrawl", "reviews/community sources"],
    "compliance_scan": ["LLM", "Tavily", "Firecrawl", "policy/regulatory sources"],
}


def build_research_context(
    db: Session,
    *,
    project_id: str,
    shop_id: str | None = None,
    industry_code: str | None = None,
    memory_selection: dict | None = None,
    limit: int = 30,
) -> dict:
    selection = normalize_memory_selection(memory_selection)
    project = db.get(Project, project_id)
    workspace = db.get(Workspace, shop_id) if shop_id else (project.workspace if project else None)
    stmt = (
        select(GmMemory)
        .where(
            GmMemory.project_id == project_id,
            GmMemory.memory_type == "research_intelligence",
            GmMemory.source_type.in_(RESEARCH_SOURCE_TYPES),
            GmMemory.status == "active",
        )
        .order_by(desc(GmMemory.created_at))
        .limit(limit * 3)
    )
    rows = db.scalars(stmt).all()

    candidates: list[GmMemory] = []
    for row in rows:
        content = row.content or {}
        content_shop_id = content.get("shop_id")
        if shop_id and content_shop_id not in {None, "", shop_id}:
            continue
        if not shop_id and content_shop_id:
            continue
        if industry_code and row.industry_code and row.industry_code != industry_code:
            continue
        candidates.append(row)
        if len(candidates) >= limit:
            break

    included: list[dict] = []
    excluded: list[dict] = []
    source_counts: Counter[str] = Counter()
    freshness_counts: Counter[str] = Counter()
    quality_scores: list[float] = []
    evidence_count = 0
    for row in candidates:
        item = _memory_context_item(row)
        source_counts[row.source_type] += 1
        freshness_counts[item["refresh_state"]] += 1
        evidence_count += item["evidence_count"]
        quality = item["evidence_quality"].get("aggregate_score")
        if isinstance(quality, int | float):
            quality_scores.append(float(quality))
        selection_reason = _selection_exclusion_reason(row.id, selection)
        if memory_is_strategy_safe(row) and not selection_reason:
            included.append(item)
        else:
            if selection_reason and selection_reason not in item["dirty_reasons"]:
                item["dirty_reasons"] = [*item["dirty_reasons"], selection_reason]
                item["strategy_safe"] = False
            excluded.append(item)

    avg_quality = round(sum(quality_scores) / len(quality_scores), 2) if quality_scores else 0.0
    return {
        "project_id": project_id,
        "shop_id": shop_id,
        "shop_name": workspace.name if workspace else None,
        "industry_code": industry_code or (workspace.industry_code if workspace else None),
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {
            "candidate_count": len(candidates),
            "included_count": len(included),
            "excluded_count": len(excluded),
            "memory_selection_mode": selection["mode"],
            "evidence_count": evidence_count,
            "average_quality": avg_quality,
            "source_counts": dict(source_counts),
            "freshness_counts": dict(freshness_counts),
            "ready_for_planning": bool(included),
        },
        "included": included[:10],
        "excluded": excluded[:10],
        "tool_needs": RESEARCH_TYPE_TOOL_NEEDS,
        "planning_guidance": _planning_guidance(included, excluded),
    }


def _selection_exclusion_reason(memory_id: str, selection: dict) -> str:
    if selection["mode"] == "none":
        return "run_memory_selection_none"
    if selection["mode"] == "manual" and memory_id not in set(selection["include_ids"]):
        return "not_selected_for_run"
    if memory_id in set(selection["exclude_ids"]):
        return "excluded_for_run"
    return ""


def _memory_context_item(row: GmMemory) -> dict:
    content = row.content or {}
    evidence = content.get("evidence") or []
    expires_at = content.get("expires_at")
    dirty_reasons = memory_dirty_reasons(row)
    return {
        "id": row.id,
        "source_type": row.source_type,
        "memory_scope": row.memory_scope,
        "memory_type": row.memory_type,
        "industry_code": row.industry_code,
        "shop_id": content.get("shop_id"),
        "summary": content.get("summary") or content.get("profile", {}).get("positioning") or content.get("report", "")[:180],
        "research_focus": content.get("research_focus") or row.source_type,
        "research_status": content.get("research_status") or "unknown",
        "review_status": content.get("review_status") or "unreviewed",
        "evidence_count": len(evidence),
        "evidence_quality": content.get("evidence_quality") or {},
        "refresh_state": research_refresh_state(expires_at),
        "expires_at": expires_at,
        "conflict_count": len(content.get("conflicts") or []),
        "dirty_reasons": dirty_reasons,
        "strategy_safe": not dirty_reasons,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _planning_guidance(included: list[dict], excluded: list[dict]) -> dict:
    included_types = sorted({item["source_type"] for item in included})
    excluded_reasons = sorted({reason for item in excluded for reason in item.get("dirty_reasons", [])})
    return {
        "use_research_types": included_types,
        "excluded_reasons": excluded_reasons,
        "instruction": (
            "Use included research by source type: store context, competitors, industry baseline, audience pain points, and compliance. "
            "Do not use excluded research unless pinned or reviewed."
        ),
    }

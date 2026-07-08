from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.data.models import GmMemory


def memory_has_unresolved_conflicts(content: dict) -> bool:
    return any((item or {}).get("status") != "resolved" for item in (content.get("conflicts") or []))


def memory_dirty_reasons(row: GmMemory) -> list[str]:
    if row.pinned:
        return []
    content = row.content or {}
    reasons: list[str] = []
    if memory_has_unresolved_conflicts(content):
        reasons.append("unresolved_conflicts")
    confidence = content.get("confidence")
    if isinstance(confidence, int | float) and confidence < 0.45:
        reasons.append("low_confidence")
    if not _has_actionable_content(content):
        reasons.append("empty_actionable_content")
    return reasons


def memory_is_strategy_safe(row: GmMemory) -> bool:
    return not memory_dirty_reasons(row)


def split_conflicting_patterns(winning_patterns: list, avoid_patterns: list) -> tuple[list, list, list[dict]]:
    winning_by_key = {_pattern_key(item): item for item in winning_patterns if _pattern_key(item)}
    avoid_by_key = {_pattern_key(item): item for item in avoid_patterns if _pattern_key(item)}
    conflict_keys = sorted(set(winning_by_key).intersection(avoid_by_key))
    conflicts = [
        {"pattern_key": key, "status": "unresolved", "reason": "pattern appears in both winning_patterns and avoid_patterns"}
        for key in conflict_keys
    ]
    return (
        [item for key, item in winning_by_key.items() if key not in conflict_keys],
        [item for key, item in avoid_by_key.items() if key not in conflict_keys],
        conflicts,
    )


def compact_gm_memory(
    db: Session,
    *,
    project_id: str,
    memory_scope: str,
    product_code: str | None = None,
    industry_code: str | None = None,
    shop_id: str | None = None,
    limit: int = 20,
) -> GmMemory | None:
    query = select(GmMemory).where(
        GmMemory.project_id == project_id,
        GmMemory.memory_scope == memory_scope,
        GmMemory.status == "active",
        GmMemory.memory_type != "summary",
        GmMemory.pinned.is_(False),
    )
    if product_code:
        query = query.where(GmMemory.product_code == product_code)
    if industry_code:
        query = query.where(GmMemory.industry_code == industry_code)
    candidates = list(db.scalars(query.order_by(desc(GmMemory.created_at)).limit(limit)).all())
    if shop_id:
        candidates = [row for row in candidates if (row.content or {}).get("shop_id") == shop_id]
    candidates = [row for row in candidates if memory_is_strategy_safe(row)]
    if not candidates:
        return None

    source_ids = [row.id for row in candidates]
    contents = [row.content or {} for row in candidates]
    summary = " / ".join(str(item.get("summary") or item.get("store_url") or item.get("source") or "").strip() for item in contents)
    summary = summary[:800] or f"Compacted {memory_scope} GM memory from {len(candidates)} entries."
    evidence = [{"memory_id": row.id, "source_type": row.source_type, "memory_type": row.memory_type} for row in candidates]
    confidence_values = [float(item.get("confidence")) for item in contents if isinstance(item.get("confidence"), int | float)]
    winning_patterns, avoid_patterns, conflicts = split_conflicting_patterns(
        [pattern for item in contents for pattern in (item.get("winning_patterns") or [])],
        [pattern for item in contents for pattern in (item.get("avoid_patterns") or [])],
    )
    compacted = GmMemory(
        project_id=project_id,
        run_id=candidates[0].run_id,
        memory_scope=memory_scope,
        product_code=product_code or candidates[0].product_code,
        industry_code=industry_code or candidates[0].industry_code,
        source_type="memory_compaction",
        score_hint=max((row.score_hint or 0 for row in candidates), default=0),
        memory_type="summary",
        status="active",
        content={
            "source": "memory_compaction",
            "scope": memory_scope,
            "shop_id": shop_id,
            "summary": summary,
            "winning_patterns": winning_patterns[:8],
            "avoid_patterns": avoid_patterns[:8],
            "conflicts": conflicts,
            "evidence": evidence,
            "source_memory_ids": source_ids,
            "metric_window": _merge_metric_windows(contents),
            "confidence": round(max(confidence_values), 2) if confidence_values else 0.55,
            "compacted_at": datetime.now(UTC).isoformat(),
        },
    )
    db.add(compacted)
    db.flush()
    for row in candidates:
        row.status = "superseded"
        content = dict(row.content or {})
        content["superseded_by_id"] = compacted.id
        row.content = content
    return compacted


def _merge_metric_windows(contents: list[dict]) -> dict:
    starts = [window.get("start") for item in contents if isinstance((window := item.get("metric_window")), dict) and window.get("start")]
    ends = [window.get("end") for item in contents if isinstance((window := item.get("metric_window")), dict) and window.get("end")]
    return {"start": min(starts) if starts else None, "end": max(ends) if ends else None}


def _pattern_key(item) -> str:
    if isinstance(item, dict):
        value = item.get("angle") or item.get("hook") or item.get("message") or item.get("variant_id")
    else:
        value = item
    return str(value or "").strip().lower()


def _has_actionable_content(content: dict) -> bool:
    return any(
        content.get(key)
        for key in (
            "summary",
            "winning_patterns",
            "avoid_patterns",
            "top_variants",
            "underperformers",
            "profile",
            "report",
            "total_revenue",
            "overall_roas",
        )
    )

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.data.models import GmMemory, Project, Workspace


def utcnow() -> datetime:
    return datetime.now(UTC)


RESEARCH_MEMORY_TTL_DAYS = 60


def _research_expires_at(generated_at: datetime) -> str:
    return (generated_at + timedelta(days=RESEARCH_MEMORY_TTL_DAYS)).isoformat()


def _evidence_for_store_url(store_url: str, *, source_type: str) -> list[dict]:
    return [
        {
            "source": source_type,
            "url": store_url,
            "summary": "Store URL used as the primary research source.",
            "fetched_at": utcnow().isoformat(),
        }
    ]


def _normalize_evidence(store_url: str, *, source_type: str, evidence: list[dict] | None) -> list[dict]:
    normalized: list[dict] = []
    for item in evidence or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or store_url)
        normalized.append({
            "source": str(item.get("source") or source_type),
            "url": url,
            "title": str(item.get("title") or ""),
            "summary": str(item.get("summary") or item.get("content") or "")[:500],
            "fetched_at": str(item.get("fetched_at") or utcnow().isoformat()),
            "status": str(item.get("status") or "ok"),
            "score": item.get("score"),
        })
    return normalized or _evidence_for_store_url(store_url, source_type=source_type)


def _research_status(evidence: list[dict], search_errors: list[str] | None) -> str:
    errors = search_errors or []
    real_sources = [item for item in evidence if item.get("source") in {"tavily", "firecrawl"} and item.get("status") == "ok"]
    if real_sources and not errors:
        return "complete"
    if real_sources:
        return "partial"
    if errors:
        return "degraded"
    return "fallback"


def _profile_summary(store_url: str, profile_data: dict) -> str:
    if isinstance(profile_data, dict):
        return str(profile_data.get("positioning") or profile_data.get("summary") or store_url)
    return store_url


def _profile_implications(profile_data: dict) -> list[str]:
    if not isinstance(profile_data, dict):
        return []
    implications: list[str] = []
    for item in profile_data.get("unique_selling_points") or []:
        implications.append(f"Emphasize differentiator: {item}")
    for item in profile_data.get("content_gaps") or []:
        implications.append(f"Test content gap: {item}")
    return implications[:8]


def _report_summary(store_url: str, report: str) -> str:
    text = " ".join(str(report or "").split())
    return text[:240] if text else f"Competitive research for {store_url}."


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


def save_shop_profile(
    db: Session,
    *,
    project_id: str,
    industry_code: str,
    store_url: str,
    profile_data: dict,
    evidence: list[dict] | None = None,
    source_queries: list[str] | None = None,
    search_errors: list[str] | None = None,
    shop_id: str | None = None,
    shop_name: str | None = None,
    research_focus: str = "full_intelligence",
) -> GmMemory:
    generated_at = utcnow()
    normalized_evidence = _normalize_evidence(store_url, source_type="shop_profile", evidence=evidence)
    status = _research_status(normalized_evidence, search_errors)
    entry = GmMemory(
        project_id=project_id,
        memory_scope="shop" if shop_id else "industry",
        industry_code=industry_code,
        source_type="shop_profile",
        memory_type="research_intelligence",
        score_hint=0.7 if status == "complete" else 0.6,
        content={
            "source": "shop_profile",
            "research_focus": research_focus,
            "scope": "shop" if shop_id else "industry",
            "shop_id": shop_id,
            "shop_name": shop_name,
            "store_url": store_url,
            "profile": profile_data,
            "summary": _profile_summary(store_url, profile_data),
            "findings": profile_data if isinstance(profile_data, dict) else {"raw_profile": profile_data},
            "strategic_implications": _profile_implications(profile_data),
            "evidence": normalized_evidence,
            "source_queries": source_queries or [f"{store_url} brand positioning target audience product catalog"],
            "search_errors": search_errors or [],
            "research_status": status,
            "metric_window": {"start": generated_at.date().isoformat(), "end": generated_at.date().isoformat()},
            "confidence": 0.72 if status == "complete" else 0.6,
            "generated_at": generated_at.isoformat(),
            "expires_at": _research_expires_at(generated_at),
        },
    )
    db.add(entry)
    db.flush()
    return entry


def save_competitor_analysis(
    db: Session,
    *,
    project_id: str,
    industry_code: str,
    store_url: str,
    analysis_markdown: str,
    evidence: list[dict] | None = None,
    source_queries: list[str] | None = None,
    search_errors: list[str] | None = None,
    shop_id: str | None = None,
    shop_name: str | None = None,
    research_focus: str = "full_intelligence",
) -> GmMemory:
    generated_at = utcnow()
    normalized_evidence = _normalize_evidence(store_url, source_type="competitor_analysis", evidence=evidence)
    status = _research_status(normalized_evidence, search_errors)
    entry = GmMemory(
        project_id=project_id,
        memory_scope="shop" if shop_id else "industry",
        industry_code=industry_code,
        source_type="competitor_analysis",
        memory_type="research_intelligence",
        score_hint=0.68 if status == "complete" else 0.58,
        content={
            "source": "competitor_analysis",
            "research_focus": research_focus,
            "scope": "shop" if shop_id else "industry",
            "shop_id": shop_id,
            "shop_name": shop_name,
            "store_url": store_url,
            "report": analysis_markdown,
            "summary": _report_summary(store_url, analysis_markdown),
            "findings": {"report": analysis_markdown},
            "strategic_implications": [_report_summary(store_url, analysis_markdown)],
            "evidence": normalized_evidence,
            "source_queries": source_queries or [f"competitors similar to {store_url} online store positioning creative patterns"],
            "search_errors": search_errors or [],
            "research_status": status,
            "metric_window": {"start": generated_at.date().isoformat(), "end": generated_at.date().isoformat()},
            "confidence": 0.68 if status == "complete" else 0.58,
            "generated_at": generated_at.isoformat(),
            "expires_at": _research_expires_at(generated_at),
        },
    )
    db.add(entry)
    db.flush()
    return entry


def list_shop_analyses(
    db: Session,
    project_id: str,
    limit: int = 20,
    shop_id: str | None = None,
) -> list[dict]:
    stmt = (
        select(GmMemory)
        .where(GmMemory.source_type.in_(["shop_profile", "competitor_analysis"]))
        .order_by(desc(GmMemory.created_at))
        .limit(limit * 3 if shop_id else limit)
    )
    if shop_id:
        stmt = stmt.where(GmMemory.memory_scope == "shop")
    else:
        stmt = stmt.where(GmMemory.project_id == project_id)
    rows = db.scalars(stmt).all()

    result: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        if shop_id and (row.content or {}).get("shop_id") != shop_id:
            continue
        store_url = (row.content or {}).get("store_url", "")
        batch_key = f"{store_url}|{row.source_type}"
        if batch_key in seen:
            continue
        seen.add(batch_key)
        summary = ""
        if row.source_type == "shop_profile":
            profile = (row.content or {}).get("profile", {})
            summary = profile.get("positioning", store_url) if isinstance(profile, dict) else store_url
        else:
            report = (row.content or {}).get("report", "")
            summary = (report[:80] + "...") if len(report) > 80 else report
        result.append({
            "id": row.id,
            "store_url": store_url,
            "industry_code": row.industry_code or "",
            "status": "completed",
            "source_type": row.source_type,
            "memory_type": row.memory_type,
            "research_status": (row.content or {}).get("research_status") or "unknown",
            "evidence_count": len((row.content or {}).get("evidence") or []),
            "expires_at": (row.content or {}).get("expires_at"),
            "summary": summary,
            "created_at": row.created_at,
        })
        if len(result) >= limit:
            break
    return result


def get_shop_analysis_pair(
    db: Session,
    industry_code: str,
    store_url: str,
) -> dict:
    """Get the most recent shop_profile and competitor_analysis for a store."""
    profile = db.scalar(
        select(GmMemory)
        .where(
            GmMemory.industry_code == industry_code,
            GmMemory.source_type == "shop_profile",
        )
        .order_by(desc(GmMemory.created_at))
        .limit(1)
    )
    competitor = db.scalar(
        select(GmMemory)
        .where(
            GmMemory.industry_code == industry_code,
            GmMemory.source_type == "competitor_analysis",
        )
        .order_by(desc(GmMemory.created_at))
        .limit(1)
    )
    # Filter by store_url in content JSON (post-query)
    profile_content = profile.content if profile and (profile.content or {}).get("store_url") == store_url else None
    competitor_content = competitor.content if competitor and (competitor.content or {}).get("store_url") == store_url else None
    return {
        "profile_content": profile_content,
        "competitor_content": competitor_content,
    }

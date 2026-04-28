from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.data.models import GmMemory, Project, Workspace


def utcnow() -> datetime:
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


def save_shop_profile(
    db: Session,
    *,
    project_id: str,
    industry_code: str,
    store_url: str,
    profile_data: dict,
) -> GmMemory:
    entry = GmMemory(
        project_id=project_id,
        memory_scope="industry",
        industry_code=industry_code,
        source_type="shop_profile",
        memory_type="store_intelligence",
        content={
            "store_url": store_url,
            "profile": profile_data,
            "generated_at": utcnow().isoformat(),
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
) -> GmMemory:
    entry = GmMemory(
        project_id=project_id,
        memory_scope="industry",
        industry_code=industry_code,
        source_type="competitor_analysis",
        memory_type="store_intelligence",
        content={
            "store_url": store_url,
            "report": analysis_markdown,
            "generated_at": utcnow().isoformat(),
        },
    )
    db.add(entry)
    db.flush()
    return entry


def list_shop_analyses(
    db: Session,
    project_id: str,
    limit: int = 20,
) -> list[dict]:
    rows = db.scalars(
        select(GmMemory)
        .where(
            GmMemory.project_id == project_id,
            GmMemory.source_type.in_(["shop_profile", "competitor_analysis"]),
        )
        .order_by(desc(GmMemory.created_at))
        .limit(limit)
    ).all()

    result: list[dict] = []
    seen: set[str] = set()
    for row in rows:
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
            "summary": summary,
            "created_at": row.created_at,
        })
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

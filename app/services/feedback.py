from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.data.models import (
    FeedbackImport,
    GmMemory,
    PerformanceSnapshot,
    Project,
    Workspace,
)
from app.schemas.contracts import FeedbackRow


def utcnow() -> datetime:
    return datetime.now(UTC)


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _weighted_score(
    *,
    ctr: float,
    cpc: float,
    cpa: float,
    roas: float,
    weights: dict,
) -> float:
    ctr_score = min(100.0, ctr * 1000.0)
    cpc_score = max(0.0, 100.0 / (1.0 + max(0.0, cpc)))
    cpa_score = max(0.0, 100.0 / (1.0 + max(0.0, cpa)))
    roas_score = min(100.0, roas * 30.0)
    return round(
        ctr_score * float(weights.get("ctr", 0.35))
        + cpc_score * float(weights.get("cpc", 0.15))
        + cpa_score * float(weights.get("cpa", 0.30))
        + roas_score * float(weights.get("roas", 0.20)),
        2,
    )


def _get_workspace_project(db: Session, workspace_name: str, project_name: str) -> tuple[Workspace, Project]:
    workspace = db.scalar(select(Workspace).where(Workspace.name == workspace_name))
    if not workspace:
        workspace = Workspace(name=workspace_name)
        db.add(workspace)
        db.flush()
    project = db.scalar(select(Project).where(Project.workspace_id == workspace.id, Project.name == project_name))
    if not project:
        project = Project(workspace_id=workspace.id, name=project_name)
        db.add(project)
        db.flush()
    return workspace, project


def import_feedback_rows(
    db: Session,
    *,
    workspace_name: str,
    project_name: str,
    rows: list[FeedbackRow],
    file_name: str,
) -> tuple[FeedbackImport, int, GmMemory | None]:
    workspace, project = _get_workspace_project(db, workspace_name, project_name)
    import_record = FeedbackImport(
        workspace_id=workspace.id,
        project_id=project.id,
        file_name=file_name,
        row_count=len(rows),
        raw_rows=[row.model_dump(mode="json") for row in rows],
    )
    db.add(import_record)

    snapshot_count = 0
    scored_rows: list[tuple[str, float]] = []
    for row in rows:
        ctr = _safe_div(row.clicks, row.impressions)
        cpc = _safe_div(row.spend, row.clicks)
        cpa = _safe_div(row.spend, row.conversions)
        roas = _safe_div(row.revenue, row.spend)
        weighted = _weighted_score(ctr=ctr, cpc=cpc, cpa=cpa, roas=roas, weights=project.metric_weights)
        scored_rows.append((row.creative_key, weighted))

        snapshot = PerformanceSnapshot(
            project_id=project.id,
            run_id=row.run_id,
            creative_key=row.creative_key,
            metrics={
                "impressions": row.impressions,
                "clicks": row.clicks,
                "spend": row.spend,
                "conversions": row.conversions,
                "revenue": row.revenue,
                "ctr": ctr,
                "cpc": cpc,
                "cpa": cpa,
                "roas": roas,
            },
            weighted_score=weighted,
            period_start=row.period_start,
            period_end=row.period_end,
        )
        db.add(snapshot)
        snapshot_count += 1

    memory = None
    if scored_rows:
        scored_rows.sort(key=lambda item: item[1], reverse=True)
        top = scored_rows[:3]
        bottom = scored_rows[-3:]
        memory = GmMemory(
            project_id=project.id,
            memory_type="strategy",
            content={
                "source": "weekly_csv_import",
                "top_creatives": top,
                "underperformers": bottom,
                "summary": "Preserve top-performing hook patterns and retire low-score variants.",
            },
        )
        db.add(memory)
    db.flush()
    return import_record, snapshot_count, memory


def project_leaderboard(db: Session, project_id: str, limit: int = 20) -> list[dict]:
    snapshots = db.scalars(
        select(PerformanceSnapshot)
        .where(PerformanceSnapshot.project_id == project_id)
        .order_by(desc(PerformanceSnapshot.created_at))
    ).all()
    merged: dict[str, dict] = {}
    for snap in snapshots:
        item = merged.setdefault(
            snap.creative_key,
            {"creative_key": snap.creative_key, "weighted_sum": 0.0, "count": 0, "metrics": []},
        )
        item["weighted_sum"] += snap.weighted_score
        item["count"] += 1
        item["metrics"].append(snap.metrics)

    ranked = []
    for creative_key, item in merged.items():
        count = max(1, item["count"])
        weighted = item["weighted_sum"] / count
        ctr = sum(m.get("ctr", 0) for m in item["metrics"]) / count
        cpc = sum(m.get("cpc", 0) for m in item["metrics"]) / count
        cpa = sum(m.get("cpa", 0) for m in item["metrics"]) / count
        roas = sum(m.get("roas", 0) for m in item["metrics"]) / count
        recommendation = "keep_and_scale" if weighted >= 60 else "retire_or_rework"
        ranked.append(
            {
                "creative_key": creative_key,
                "weighted_score": round(weighted, 2),
                "ctr": round(ctr, 4),
                "cpc": round(cpc, 4),
                "cpa": round(cpa, 4),
                "roas": round(roas, 4),
                "recommendation": recommendation,
            }
        )
    ranked.sort(key=lambda item: item["weighted_score"], reverse=True)
    return ranked[:limit]


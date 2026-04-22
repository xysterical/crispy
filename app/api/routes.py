from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.data.models import PipelineRun, StageTask
from app.data.session import get_db
from app.schemas.api import (
    FeedbackImportRequest,
    FeedbackImportResponse,
    LeaderboardItem,
    LeaderboardResponse,
    PersonaPatchRequest,
    PersonaView,
    ReviewActionRequest,
    RunCreateRequest,
    RunView,
    StageTaskView,
)
from app.schemas.contracts import ComplianceLevel, ConversionForecast, ScoreCard
from app.services.feedback import import_feedback_rows, project_leaderboard
from app.services.personas import get_persona, update_persona
from app.services.runs import approve_stage, create_run, get_run, latest_scorecard, reject_stage


router = APIRouter()


def _serialize_run(db: Session, run: PipelineRun) -> RunView:
    tasks = db.scalars(
        select(StageTask).where(StageTask.run_id == run.id).order_by(StageTask.created_at.asc())
    ).all()
    task_views = [
        StageTaskView(
            id=task.id,
            stage_name=task.stage_name,
            status=task.status,
            attempt=task.attempt,
            review_notes=task.review_notes,
            output_payload=task.output_payload or {},
            error_message=task.error_message,
            started_at=task.started_at,
            completed_at=task.completed_at,
        )
        for task in tasks
    ]

    scorecard_model = latest_scorecard(db, run.id)
    scorecard = None
    forecast = None
    if scorecard_model:
        scorecard = ScoreCard(
            sub_scores=scorecard_model.sub_scores,
            total_score=scorecard_model.total_score,
            risk_labels=scorecard_model.risk_labels,
            explanation=scorecard_model.explanation,
            compliance_level=ComplianceLevel(scorecard_model.compliance_level),
            ai_artifact_score=scorecard_model.ai_artifact_score,
        )
        forecast = ConversionForecast.model_validate(scorecard_model.forecast)

    return RunView(
        id=run.id,
        status=run.status,
        current_stage=run.current_stage,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        product_id=run.product_id,
        campaign_id=run.campaign_id,
        market=run.market,
        locale=run.locale,
        model_provider=run.model_provider,
        model_name=run.model_name,
        budget_used=run.budget_used,
        variant_count=run.variant_count,
        created_at=run.created_at,
        updated_at=run.updated_at,
        stage_tasks=task_views,
        latest_scorecard=scorecard,
        latest_forecast=forecast,
    )


@router.get("/", response_class=HTMLResponse)
def dashboard(db: Session = Depends(get_db)) -> str:
    runs = db.scalars(select(PipelineRun).order_by(desc(PipelineRun.created_at)).limit(30)).all()
    rows = "\n".join(
        f"<tr><td>{run.id}</td><td>{run.status}</td><td>{run.current_stage}</td><td>{run.updated_at}</td></tr>"
        for run in runs
    )
    return f"""
    <html>
      <head><title>crispy dashboard</title></head>
      <body>
        <h1>crispy pipeline dashboard</h1>
        <p>Single-user MVP dashboard for manual stage review and ROI loop verification.</p>
        <table border="1" cellpadding="6">
          <tr><th>Run ID</th><th>Status</th><th>Current Stage</th><th>Updated At</th></tr>
          {rows}
        </table>
      </body>
    </html>
    """


@router.post("/runs", response_model=RunView)
def create_pipeline_run(payload: RunCreateRequest, db: Session = Depends(get_db)) -> RunView:
    run = create_run(db, payload)
    db.commit()
    db.refresh(run)
    return _serialize_run(db, run)


@router.get("/runs/{run_id}", response_model=RunView)
def get_pipeline_run(run_id: str, db: Session = Depends(get_db)) -> RunView:
    try:
        run = get_run(db, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _serialize_run(db, run)


@router.post("/runs/{run_id}/advance", response_model=RunView)
def advance_pipeline_run(run_id: str, payload: ReviewActionRequest, db: Session = Depends(get_db)) -> RunView:
    try:
        run = approve_stage(db, run_id, notes=payload.notes)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _serialize_run(db, run)


@router.post("/runs/{run_id}/reject", response_model=RunView)
def reject_pipeline_run(run_id: str, payload: ReviewActionRequest, db: Session = Depends(get_db)) -> RunView:
    try:
        run = reject_stage(db, run_id, notes=payload.notes)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _serialize_run(db, run)


@router.post("/feedback/import", response_model=FeedbackImportResponse)
def import_feedback(payload: FeedbackImportRequest, db: Session = Depends(get_db)) -> FeedbackImportResponse:
    import_record, snapshots, memory = import_feedback_rows(
        db,
        workspace_name=payload.workspace_name,
        project_name=payload.project_name,
        rows=payload.rows,
        file_name=payload.file_name,
    )
    db.commit()
    return FeedbackImportResponse(
        import_id=import_record.id,
        rows=import_record.row_count,
        snapshots_created=snapshots,
        memory_entry_id=memory.id if memory else None,
    )


@router.get("/projects/{project_id}/leaderboard", response_model=LeaderboardResponse)
def leaderboard(project_id: str, db: Session = Depends(get_db)) -> LeaderboardResponse:
    ranking = [LeaderboardItem(**item) for item in project_leaderboard(db, project_id)]
    return LeaderboardResponse(project_id=project_id, ranking=ranking)


@router.get("/personas/{agent_name}", response_model=PersonaView)
def read_agent_persona(agent_name: str, db: Session = Depends(get_db)) -> PersonaView:
    try:
        content, version, source_path = get_persona(db, agent_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PersonaView(agent_name=agent_name, content=content, version=version, source_path=source_path)


@router.patch("/personas/{agent_name}", response_model=PersonaView)
def patch_agent_persona(
    agent_name: str,
    payload: PersonaPatchRequest,
    db: Session = Depends(get_db),
) -> PersonaView:
    content, version, source_path = update_persona(db, agent_name, payload.content, payload.changed_by)
    db.commit()
    return PersonaView(agent_name=agent_name, content=content, version=version, source_path=source_path)


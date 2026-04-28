from __future__ import annotations

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.data.models import RunTemplate


def list_run_templates(db: Session, workspace_name: str) -> list[RunTemplate]:
    return list(
        db.scalars(
            select(RunTemplate)
            .where(RunTemplate.workspace_name == workspace_name)
            .order_by(RunTemplate.updated_at.desc())
        ).all()
    )


def get_run_template(db: Session, template_id: str) -> RunTemplate:
    template = db.get(RunTemplate, template_id)
    if not template:
        raise ValueError(f"run template not found: {template_id}")
    return template


def create_run_template(db: Session, workspace_name: str, name: str, config_json: dict | None = None, is_shared: bool = False) -> RunTemplate:
    existing = db.scalar(
        select(RunTemplate).where(
            RunTemplate.workspace_name == workspace_name,
            RunTemplate.name == name,
        )
    )
    if existing:
        raise ValueError(f"run template already exists: {name}")
    template = RunTemplate(
        workspace_name=workspace_name,
        name=name,
        config_json=config_json or {},
        is_shared=is_shared,
    )
    db.add(template)
    db.flush()
    return template


def update_run_template(db: Session, template_id: str, **kwargs) -> RunTemplate:
    template = get_run_template(db, template_id)
    for key, value in kwargs.items():
        if value is not None and hasattr(template, key):
            setattr(template, key, value)
    db.flush()
    return template


def delete_run_template(db: Session, template_id: str) -> None:
    template = get_run_template(db, template_id)
    db.delete(template)
    db.flush()

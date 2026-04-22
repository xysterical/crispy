from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.personas import ensure_default_personas, read_persona, write_persona
from app.data.models import PersonaVersion


def get_persona(db: Session, agent_name: str) -> tuple[str, int, str]:
    ensure_default_personas()
    content = read_persona(agent_name)
    latest_version = db.scalar(
        select(func.max(PersonaVersion.version)).where(PersonaVersion.agent_name == agent_name)
    )
    version = int(latest_version or 1)
    source_path = f"personas/{agent_name}.md"
    return content, version, source_path


def update_persona(db: Session, agent_name: str, content: str, changed_by: str) -> tuple[str, int, str]:
    ensure_default_personas()
    source_path = write_persona(agent_name, content)
    latest_version = db.scalar(
        select(func.max(PersonaVersion.version)).where(PersonaVersion.agent_name == agent_name)
    )
    version = int(latest_version or 0) + 1
    db.add(
        PersonaVersion(
            agent_name=agent_name,
            version=version,
            source_path=source_path,
            content=content,
            changed_by=changed_by,
        )
    )
    db.flush()
    return content, version, source_path


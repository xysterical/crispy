from __future__ import annotations

from pathlib import Path

from app.agents.registry import AGENT_SPECS, get_agent_spec
from app.core.config import get_settings


def _legacy_flat_path(agent_name: str) -> Path:
    return get_settings().personas_dir / f"{agent_name}.md"


def ensure_default_personas() -> None:
    settings = get_settings()
    settings.personas_dir.mkdir(parents=True, exist_ok=True)
    for spec in AGENT_SPECS:
        path = settings.personas_dir / spec.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        legacy_path = _legacy_flat_path(spec.name)
        if legacy_path.exists() and not path.exists():
            path.write_text(legacy_path.read_text(encoding="utf-8"), encoding="utf-8")
            continue
        if not path.exists():
            path.write_text(spec.default_content, encoding="utf-8")


def persona_path(agent_name: str) -> Path:
    spec = get_agent_spec(agent_name)
    return get_settings().personas_dir / spec.relative_path


def list_personas() -> list[dict]:
    ensure_default_personas()
    settings = get_settings()
    rows: list[dict] = []
    for spec in AGENT_SPECS:
        path = settings.personas_dir / spec.relative_path
        rows.append(
            {
                "agent_name": spec.name,
                "display_name": spec.display_name,
                "stage": spec.stage,
                "role": spec.role,
                "order": spec.order,
                "source_path": str(path),
            }
        )
    return rows


def read_persona(agent_name: str) -> str:
    ensure_default_personas()
    path = persona_path(agent_name)
    if not path.exists():
        raise FileNotFoundError(f"persona not found: {agent_name}")
    return path.read_text(encoding="utf-8")


def write_persona(agent_name: str, content: str) -> str:
    ensure_default_personas()
    path = persona_path(agent_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path)

from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings


DEFAULT_PERSONAS: dict[str, str] = {
    "gm_orchestrator": """# GM Orchestrator
- Focus on ROI optimization and strategy memory.
- Convert feedback into actionable next-round directives.
- Enforce stage quality gates and data discipline.
""",
    "research_agent": """# Research Agent
- Produce market insights with evidence references.
- Prioritize audience pain points and competitor observations.
""",
    "ideation_agent": """# Ideation Agent
- Generate hook matrix and creative hypotheses.
- Keep outputs executable and variant-oriented.
""",
    "generation_agent": """# Generation Agent
- Produce ad copy, image prompts and video sample plan.
- Follow en-US market defaults and compliance constraints.
""",
    "scoring_agent": """# Scoring Agent
- Evaluate creative quality with interpretable sub-scores.
- Output forecasting score with confidence and action.
""",
    "compliance_agent": """# Compliance Agent
- Detect legal/brand risk and AI-artifact quality issues.
- Classify risk into low/medium/high with explicit reasons.
""",
}


def ensure_default_personas() -> None:
    settings = get_settings()
    settings.personas_dir.mkdir(parents=True, exist_ok=True)
    for agent_name, content in DEFAULT_PERSONAS.items():
        path = settings.personas_dir / f"{agent_name}.md"
        if not path.exists():
            path.write_text(content, encoding="utf-8")


def persona_path(agent_name: str) -> Path:
    return get_settings().personas_dir / f"{agent_name}.md"


def read_persona(agent_name: str) -> str:
    ensure_default_personas()
    path = persona_path(agent_name)
    if not path.exists():
        raise FileNotFoundError(f"persona not found: {agent_name}")
    return path.read_text(encoding="utf-8")


def write_persona(agent_name: str, content: str) -> str:
    ensure_default_personas()
    path = persona_path(agent_name)
    path.write_text(content, encoding="utf-8")
    return str(path)


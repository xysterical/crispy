from __future__ import annotations

from app.data.models import StageName


STAGE_ORDER: list[str] = [
    StageName.RESEARCH.value,
    StageName.IDEATION.value,
    StageName.GENERATION.value,
    StageName.SCORING.value,
]


def next_stage(current_stage: str | None) -> str | None:
    if current_stage is None:
        return STAGE_ORDER[0]
    if current_stage not in STAGE_ORDER:
        return None
    idx = STAGE_ORDER.index(current_stage)
    if idx + 1 >= len(STAGE_ORDER):
        return None
    return STAGE_ORDER[idx + 1]


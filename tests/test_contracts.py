from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.contracts import FeedbackRow, ResearchReport


def test_research_report_contract_accepts_required_shape():
    report = ResearchReport(
        market_insights=["insight"],
        audience_segments=["segment"],
        competitor_observations=["obs"],
        pain_points=["pain"],
        forbidden_claims=["claim"],
        tone_guidance="tone",
        evidence=[{"source": "s", "summary": "x", "url": "https://example.com"}],
    )
    assert report.evidence[0].url == "https://example.com"


def test_feedback_row_contract_rejects_negative_metrics():
    with pytest.raises(ValidationError):
        FeedbackRow(
            project_name="p",
            creative_key="c1",
            impressions=-1,
        )


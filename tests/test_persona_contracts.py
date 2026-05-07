from __future__ import annotations

from app.agents.persona_contracts import parse_persona_contract


def test_parse_persona_contract_extracts_known_sections():
    content = """# Planning Agent
## Mission
Turn inputs into a commercially sharp plan.

## Must Output
- Strategic angles
- Claim boundaries

## Cannot Do
- Invent product facts

## Handoff In
- Intake facts
- GM lessons

## Handoff Out
- Planning brief

## Verification
- Output should be review-ready
"""
    contract = parse_persona_contract(content)

    assert contract["title"] == "Planning Agent"
    assert contract["mission"] == "Turn inputs into a commercially sharp plan."
    assert contract["must_output"] == ["Strategic angles", "Claim boundaries"]
    assert contract["cannot_do"] == ["Invent product facts"]
    assert contract["handoff_in"] == ["Intake facts", "GM lessons"]
    assert contract["handoff_out"] == ["Planning brief"]
    assert contract["verification"] == ["Output should be review-ready"]


def test_parse_persona_contract_preserves_unmapped_sections_as_additional_guidance():
    content = """# Agent
## Mission
Keep outputs tight.

## Custom Notes
- Prefer concrete language
"""
    contract = parse_persona_contract(content)

    assert contract["mission"] == "Keep outputs tight."
    assert "## Custom Notes" in contract["additional_guidance"]
    assert "Prefer concrete language" in contract["additional_guidance"]


def test_parse_persona_contract_preserves_top_level_guidance_without_sections():
    content = """# Product Research Agent
- Updated from dashboard.
- Keep findings source-backed.
"""
    contract = parse_persona_contract(content)

    assert contract["title"] == "Product Research Agent"
    assert "Updated from dashboard" in contract["additional_guidance"]
    assert "Keep findings source-backed" in contract["additional_guidance"]

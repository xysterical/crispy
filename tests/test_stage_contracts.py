from __future__ import annotations

from app.agents.registry import STAGE_ASSIGNMENTS, STAGE_CONTRACT_VERSION, stage_agent, stage_collaborators
from app.data.models import StageName
from app.orchestrator.stage_contracts import (
    STAGE_CONTRACTS,
    all_stage_contracts,
    get_stage_contract,
    stage_contracts_for_plan,
)
from app.orchestrator.state_machine import PIPELINE_STAGE_PLANS
from app.services.stage_execution import runtime_stage_names
from app.services.stage_inputs import STAGE_OUTPUT_INPUTS, stage_input_keys_for_contract


def test_every_pipeline_stage_has_contract():
    stage_names = {stage for plan in PIPELINE_STAGE_PLANS.values() for stage in plan}

    assert stage_names == set(STAGE_CONTRACTS)


def test_stage_contracts_preserve_agent_assignments():
    for stage_name, assignment in STAGE_ASSIGNMENTS.items():
        contract = get_stage_contract(stage_name)
        assert contract.lead_agent == assignment.lead_agent
        assert contract.collaborators == assignment.collaborators
        assert contract.contract_version == STAGE_CONTRACT_VERSION
        assert contract.lead_agent == stage_agent(stage_name)
        assert contract.collaborators == stage_collaborators(stage_name)


def test_stage_contracts_are_complete_enough_to_drive_next_refactor():
    valid_capabilities = {
        "text_generation",
        "image_understanding",
        "video_understanding",
        "image_generation",
        "reference_image_edit",
        "video_generation",
    }
    valid_approval_defaults = {"manual", "auto_strategy", "auto_full"}

    for contract in all_stage_contracts():
        assert contract.stage_name
        assert contract.runtime_handler.startswith("run_")
        assert contract.produces
        assert contract.review_focus
        assert contract.success_criteria
        assert set(contract.required_capabilities).issubset(valid_capabilities)
        assert contract.human_approval_default in valid_approval_defaults


def test_stage_contracts_for_plan_preserve_stage_order():
    for pipeline_mode, stage_plan in PIPELINE_STAGE_PLANS.items():
        contracts = stage_contracts_for_plan(pipeline_mode)
        assert [contract.stage_name for contract in contracts] == stage_plan


def test_visual_and_evaluation_contracts_capture_gate_dependencies():
    visual = get_stage_contract(StageName.VISUAL_QUALITY_ASSESSMENT.value)
    evaluation = get_stage_contract(StageName.EVALUATION_SELECTION.value)

    assert "variants" in visual.required_inputs
    assert "social_review_contract" in visual.optional_inputs
    assert "visual_quality" in evaluation.required_inputs
    assert "winner_selection" in evaluation.produces


def test_stage_input_bindings_cover_contract_required_inputs():
    for contract in all_stage_contracts():
        input_keys = stage_input_keys_for_contract(contract.stage_name)
        assert set(contract.required_inputs).issubset(input_keys)


def test_stage_input_bindings_only_reference_known_stages():
    known_stages = set(STAGE_CONTRACTS)
    for stage_name, bindings in STAGE_OUTPUT_INPUTS.items():
        assert stage_name in known_stages
        assert set(bindings.values()).issubset(known_stages)


def test_runtime_dispatch_covers_every_stage_contract():
    assert runtime_stage_names() == set(STAGE_CONTRACTS)

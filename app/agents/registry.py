from __future__ import annotations

from dataclasses import dataclass


STAGE_CONTRACT_VERSION = "commercial-pilot-v2"


@dataclass(frozen=True, slots=True)
class AgentSpec:
    name: str
    display_name: str
    stage: str
    role: str
    relative_path: str
    order: int


@dataclass(frozen=True, slots=True)
class StageAssignment:
    lead_agent: str
    collaborators: tuple[str, ...] = ()
    contract_version: str = STAGE_CONTRACT_VERSION


AGENT_SPECS: tuple[AgentSpec, ...] = (
    AgentSpec(
        name="gm_orchestrator",
        display_name="GM Orchestrator",
        stage="manager",
        role="run_governance",
        relative_path="gm/gm_orchestrator.md",
        order=0,
    ),
    AgentSpec(
        name="product_research_agent",
        display_name="Product Research Agent",
        stage="research",
        role="product_market_research",
        relative_path="stages/01_product_research_agent.md",
        order=10,
    ),
    AgentSpec(
        name="shop_analyst",
        display_name="Research Intelligence Agent",
        stage="research",
        role="store_industry_research",
        relative_path="stages/shop_analyst.md",
        order=15,
    ),
    AgentSpec(
        name="planning_agent",
        display_name="Planning Agent",
        stage="planning",
        role="creative_strategy",
        relative_path="stages/02_planning_agent.md",
        order=20,
    ),
    AgentSpec(
        name="variant_strategy_agent",
        display_name="Variant Strategy Agent",
        stage="divergence",
        role="variant_design",
        relative_path="stages/03_variant_strategy_agent.md",
        order=30,
    ),
    AgentSpec(
        name="copy_image_agent",
        display_name="Copy Image Agent",
        stage="copy_image_generation",
        role="copy_and_image_generation",
        relative_path="stages/04_copy_image_agent.md",
        order=40,
    ),
    AgentSpec(
        name="video_script_agent",
        display_name="Video Script Agent",
        stage="video_scripting",
        role="video_script_generation",
        relative_path="stages/05_video_script_agent.md",
        order=50,
    ),
    AgentSpec(
        name="storyboard_agent",
        display_name="Storyboard Agent",
        stage="storyboard_image_generation",
        role="storyboard_generation",
        relative_path="stages/06_storyboard_agent.md",
        order=60,
    ),
    AgentSpec(
        name="video_generation_agent",
        display_name="Video Generation Agent",
        stage="video_generation",
        role="video_generation",
        relative_path="stages/07_video_generation_agent.md",
        order=70,
    ),
    AgentSpec(
        name="visual_qa_agent",
        display_name="Visual QA Agent",
        stage="visual_quality_assessment",
        role="multimodal_visual_quality_gate",
        relative_path="stages/08_visual_qa_agent.md",
        order=80,
    ),
    AgentSpec(
        name="evaluation_agent",
        display_name="Evaluation Agent",
        stage="evaluation_selection",
        role="variant_ranking",
        relative_path="stages/08_evaluation_agent.md",
        order=90,
    ),
    AgentSpec(
        name="compliance_agent",
        display_name="Compliance Agent",
        stage="evaluation_selection",
        role="compliance_guard",
        relative_path="stages/09_compliance_agent.md",
        order=100,
    ),
)


STAGE_ASSIGNMENTS: dict[str, StageAssignment] = {
    "intake": StageAssignment(lead_agent="gm_orchestrator"),
    "planning": StageAssignment(lead_agent="planning_agent", collaborators=("product_research_agent", "gm_orchestrator")),
    "divergence": StageAssignment(lead_agent="variant_strategy_agent", collaborators=("planning_agent",)),
    "copy_image_generation": StageAssignment(lead_agent="copy_image_agent", collaborators=("gm_orchestrator",)),
    "video_scripting": StageAssignment(lead_agent="video_script_agent", collaborators=("gm_orchestrator",)),
    "storyboard_image_generation": StageAssignment(lead_agent="storyboard_agent", collaborators=("video_script_agent",)),
    "video_generation": StageAssignment(lead_agent="video_generation_agent", collaborators=("storyboard_agent",)),
    "visual_quality_assessment": StageAssignment(
        lead_agent="visual_qa_agent",
        collaborators=("copy_image_agent", "storyboard_agent", "video_generation_agent", "compliance_agent"),
    ),
    "evaluation_selection": StageAssignment(lead_agent="evaluation_agent", collaborators=("compliance_agent", "gm_orchestrator")),
}


def get_agent_spec(agent_name: str) -> AgentSpec:
    for spec in AGENT_SPECS:
        if spec.name == agent_name:
            return spec
    raise KeyError(f"unknown agent: {agent_name}")


def stage_assignment(stage_name: str) -> StageAssignment:
    return STAGE_ASSIGNMENTS.get(stage_name, StageAssignment(lead_agent="gm_orchestrator"))


def stage_agent(stage_name: str) -> str:
    return stage_assignment(stage_name).lead_agent


def stage_collaborators(stage_name: str) -> tuple[str, ...]:
    return stage_assignment(stage_name).collaborators

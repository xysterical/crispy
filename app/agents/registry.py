from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentSpec:
    name: str
    display_name: str
    stage: str
    role: str
    relative_path: str
    default_content: str
    order: int


AGENT_SPECS: tuple[AgentSpec, ...] = (
    AgentSpec(
        name="gm_orchestrator",
        display_name="GM Orchestrator",
        stage="manager",
        role="global_strategy",
        relative_path="gm/gm_orchestrator.md",
        order=0,
        default_content="""# GM Orchestrator
- Own stage gating and final decision quality.
- Convert historical feedback into next-round strategy memory.
- Prioritize ROI and enforce compliance hard gates.
- Track model usage and budget spend for each run.
""",
    ),
    AgentSpec(
        name="research_agent",
        display_name="Research Agent",
        stage="research",
        role="market_research",
        relative_path="stages/01_research_agent.md",
        order=10,
        default_content="""# Research Agent
- Produce practical US market insights with clear evidence links.
- Identify competitor patterns, audience segments, and risk claims.
- Output concise, execution-ready market brief.
""",
    ),
    AgentSpec(
        name="ideation_agent",
        display_name="Ideation Agent",
        stage="ideation",
        role="creative_planning",
        relative_path="stages/02_ideation_agent.md",
        order=20,
        default_content="""# Ideation Agent
- Create diverse hook matrix with explicit emotional targets.
- Build 8 hypothesis-led variants with clear rationale.
- Respect forbidden claim constraints from research stage.
""",
    ),
    AgentSpec(
        name="generation_agent",
        display_name="Generation Agent",
        stage="generation",
        role="asset_generation",
        relative_path="stages/03_generation_agent.md",
        order=30,
        default_content="""# Generation Agent
- Generate Meta-first ad copy, image prompts, and video sample plan.
- Maintain en-US tone and direct response style.
- Keep creative outputs auditable and variant-tagged.
""",
    ),
    AgentSpec(
        name="scoring_agent",
        display_name="Scoring Agent",
        stage="scoring",
        role="quality_scoring",
        relative_path="stages/04_scoring_agent.md",
        order=40,
        default_content="""# Scoring Agent
- Score quality across attraction, clarity, brand alignment, compliance, and AI naturalness.
- Provide explainable reasons for each sub-score.
- Output conversion forecast (0-100) with confidence.
""",
    ),
    AgentSpec(
        name="compliance_agent",
        display_name="Compliance Agent",
        stage="scoring",
        role="compliance_guard",
        relative_path="stages/05_compliance_agent.md",
        order=50,
        default_content="""# Compliance Agent
- Enforce high-risk hard block and medium-risk manual review policy.
- Flag legal exaggerations and synthetic AI-feel artifacts.
- Return explicit risk reasons and review recommendations.
""",
    ),
)


def get_agent_spec(agent_name: str) -> AgentSpec:
    for spec in AGENT_SPECS:
        if spec.name == agent_name:
            return spec
    raise KeyError(f"unknown agent: {agent_name}")


def stage_agent(stage_name: str) -> str:
    mapping = {
        "research": "research_agent",
        "ideation": "ideation_agent",
        "generation": "generation_agent",
        "scoring": "scoring_agent",
    }
    return mapping.get(stage_name, "gm_orchestrator")


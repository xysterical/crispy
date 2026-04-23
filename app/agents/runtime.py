from __future__ import annotations

from dataclasses import dataclass, field

from app.providers.llm import ProviderRegistry
from app.providers.media import LocalMediaProvider
from app.schemas.contracts import (
    ComplianceLevel,
    ConversionForecast,
    CreativeBlueprint,
    CreativeBundle,
    CreativeHypothesis,
    CopyVariant,
    HookItem,
    ImageAssetRef,
    ResearchReport,
    ScoreBreakdown,
    ScoreCard,
    VideoPlan,
)
from app.scoring.engine import ComplianceCheckResult, compliance_check, score_bundle


@dataclass(slots=True)
class StageOutput:
    payload: dict
    model_used: str | None = None
    estimated_cost: float = 0.0
    artifacts: list[dict] = field(default_factory=list)
    scorecard: ScoreCard | None = None
    forecast: ConversionForecast | None = None


class AgentsRuntime:
    def __init__(self) -> None:
        self.providers = ProviderRegistry()
        self.media = LocalMediaProvider()

    def run_research(
        self,
        run_id: str,
        context: dict,
        *,
        provider: str,
        model: str,
        runtime_config: dict | None = None,
    ) -> StageOutput:
        prompt = (
            "Summarize US pet product market, audience pain points, competitor hooks "
            f"for campaign context: {context}"
        )
        llm = self.providers.get(provider)
        runtime_config = runtime_config or {}
        response = llm.complete(
            prompt,
            model=model,
            api_base_url=runtime_config.get("api_base_url"),
            api_key=runtime_config.get("api_key"),
            extra=runtime_config.get("extra"),
        )
        report = ResearchReport(
            market_insights=[
                "Pet owners prefer clinically-backed safety claims and practical daily-use messaging.",
                "Short-form social content with immediate benefit framing outperforms long intros.",
            ],
            audience_segments=["First-time pet parents", "Busy urban dog owners", "Cat owners focused on hygiene"],
            competitor_observations=[
                "Competitors overuse generic emotional claims without evidence.",
                "Top performing creatives combine before/after framing with concrete feature proof.",
            ],
            pain_points=["Odor control", "Time-consuming cleanup", "Pet anxiety during routine care"],
            forbidden_claims=["Guaranteed medical cure", "Vet approved without documentation"],
            tone_guidance="Confident, practical, and evidence-aware en-US copy style.",
            evidence=[
                {
                    "source": "simulated_insight",
                    "summary": response.text,
                    "url": "https://example.com/market-insight",
                }
            ],
        )
        uri = self.media.write_text_artifact(run_id, "research_report.md", report.model_dump_json(indent=2))
        return StageOutput(
            payload=report.model_dump(),
            model_used=response.model_used,
            estimated_cost=response.estimated_cost,
            artifacts=[{"type": "research_report", "uri": uri, "payload": report.model_dump()}],
        )

    def run_ideation(
        self,
        run_id: str,
        research: ResearchReport,
        *,
        variant_count: int,
        provider: str,
        model: str,
        runtime_config: dict | None = None,
    ) -> StageOutput:
        prompt = f"Build ad hooks and hypotheses from research: {research.model_dump_json()}"
        llm = self.providers.get(provider)
        runtime_config = runtime_config or {}
        response = llm.complete(
            prompt,
            model=model,
            api_base_url=runtime_config.get("api_base_url"),
            api_key=runtime_config.get("api_key"),
            extra=runtime_config.get("extra"),
        )

        hooks = [
            HookItem(angle="time-saving", hook="Cut cleanup time in half before work", target_emotion="relief"),
            HookItem(angle="odor-proof", hook="Stop litter smell before guests notice", target_emotion="confidence"),
            HookItem(angle="comfort", hook="Gentle routine your pet actually accepts", target_emotion="trust"),
        ]
        hypotheses = [
            CreativeHypothesis(
                hypothesis_id=f"H{i + 1}",
                message=f"Variant {i + 1} emphasizes measurable convenience and comfort.",
                rationale="Combines immediate utility with low-friction daily adoption.",
            )
            for i in range(variant_count)
        ]
        blueprint = CreativeBlueprint(
            audience_priority=research.audience_segments[:3],
            hook_matrix=hooks,
            hypotheses=hypotheses,
            variant_plan=[f"V{i + 1}" for i in range(variant_count)],
            narrative_constraints=research.forbidden_claims,
            default_variant_count=variant_count,
        )
        uri = self.media.write_text_artifact(run_id, "creative_blueprint.md", blueprint.model_dump_json(indent=2))
        return StageOutput(
            payload=blueprint.model_dump(),
            model_used=response.model_used,
            estimated_cost=response.estimated_cost,
            artifacts=[{"type": "creative_blueprint", "uri": uri, "payload": blueprint.model_dump()}],
        )

    def run_generation(
        self,
        run_id: str,
        blueprint: CreativeBlueprint,
        *,
        provider: str,
        model: str,
        runtime_config: dict | None = None,
    ) -> StageOutput:
        prompt = f"Generate ad copy and media plan from blueprint: {blueprint.model_dump_json()}"
        llm = self.providers.get(provider)
        runtime_config = runtime_config or {}
        response = llm.complete(
            prompt,
            model=model,
            api_base_url=runtime_config.get("api_base_url"),
            api_key=runtime_config.get("api_key"),
            extra=runtime_config.get("extra"),
        )

        copy_variants = []
        image_assets = []
        for idx, item in enumerate(blueprint.variant_plan):
            copy = CopyVariant(
                variant_id=item,
                primary_text=f"{item}: Make daily pet care faster with less stress and cleaner results.",
                headline=f"{item}: Cleaner Home, Happier Pet",
                description="Built for busy owners who need practical results in minutes.",
                call_to_action="Shop Now",
            )
            copy_variants.append(copy)
            image_path = self.media.reserve_binary_artifact(run_id, f"image_{idx + 1}.png")
            image_assets.append(
                ImageAssetRef(
                    variant_id=item,
                    uri=image_path,
                    aspect_ratio="1:1",
                    prompt=f"Photoreal pet product setup for {item}, bright natural light, clean home.",
                )
            )

        video_plan = VideoPlan(
            hook="Most pet owners waste 20+ minutes daily on cleanup. Here's the 60-second fix.",
            script=(
                "Hook: show daily mess. "
                "Problem: owner frustration and odor. "
                "Solution: demonstrate product use in three shots. "
                "Proof: before/after scene. CTA: try it today."
            ),
            storyboard=[
                "Shot 1: messy scene and owner reaction",
                "Shot 2: quick product demonstration",
                "Shot 3: clean result and calm pet",
            ],
            shot_list=["close-up product", "wide room cleanup", "owner testimonial line"],
            localization_notes=["Use en-US idioms", "Avoid unsupported medical claims"],
            output_ratio="9:16",
        )
        video_uri = self.media.reserve_binary_artifact(run_id, "video_sample.mp4")
        bundle = CreativeBundle(
            copy_variants=copy_variants,
            image_assets=image_assets,
            video_plan=video_plan,
            video_sample_uri=video_uri,
        )
        uri = self.media.write_text_artifact(run_id, "creative_bundle.md", bundle.model_dump_json(indent=2))
        artifacts = [{"type": "creative_bundle", "uri": uri, "payload": bundle.model_dump()}]
        artifacts.extend({"type": "image", "uri": image.uri, "payload": image.model_dump()} for image in image_assets)
        artifacts.append({"type": "video_sample", "uri": video_uri, "payload": video_plan.model_dump()})
        return StageOutput(
            payload=bundle.model_dump(),
            model_used=response.model_used,
            estimated_cost=response.estimated_cost,
            artifacts=artifacts,
        )

    def run_scoring(
        self,
        run_id: str,
        bundle: CreativeBundle,
        *,
        provider: str,
        model: str,
        runtime_config: dict | None = None,
    ) -> StageOutput:
        prompt = f"Evaluate quality and compliance for bundle: {bundle.model_dump_json()}"
        llm = self.providers.get(provider)
        runtime_config = runtime_config or {}
        response = llm.complete(
            prompt,
            model=model,
            api_base_url=runtime_config.get("api_base_url"),
            api_key=runtime_config.get("api_key"),
            extra=runtime_config.get("extra"),
        )

        compliance_result = compliance_check(bundle)
        scorecard, forecast = score_bundle(bundle, compliance_result)
        payload = {
            "scorecard": scorecard.model_dump(),
            "forecast": forecast.model_dump(),
            "compliance": compliance_result.model_dump(),
        }
        uri = self.media.write_text_artifact(run_id, "scorecard.md", scorecard.model_dump_json(indent=2))
        return StageOutput(
            payload=payload,
            model_used=response.model_used,
            estimated_cost=response.estimated_cost,
            artifacts=[{"type": "scorecard", "uri": uri, "payload": payload}],
            scorecard=scorecard,
            forecast=forecast,
        )


def make_fallback_scorecard() -> ScoreCard:
    return ScoreCard(
        sub_scores=ScoreBreakdown(
            attraction=50,
            clarity=50,
            brand_alignment=50,
            compliance=50,
            ai_naturalness=50,
        ),
        total_score=50,
        risk_labels=["insufficient_data"],
        explanation={"summary": "Fallback score due to missing generation output."},
        compliance_level=ComplianceLevel.MEDIUM,
        ai_artifact_score=50,
    )


def make_fallback_forecast() -> ConversionForecast:
    return ConversionForecast(
        score_0_100=50,
        confidence_0_1=0.1,
        drivers=["insufficient_data"],
        recommended_action="regenerate_with_full_input",
    )

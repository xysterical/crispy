from __future__ import annotations

from dataclasses import dataclass, field

from app.providers.llm import ProviderRegistry
from app.providers.media import LocalMediaProvider
from app.schemas.contracts import (
    ComplianceLevel,
    ConversionForecast,
    CopyImageBundle,
    CopyVariant,
    EvaluationResult,
    ImageAssetRef,
    PlanningBrief,
    ProductIntake,
    RankedVariant,
    ScoreBreakdown,
    ScoreCard,
    SelectedDeliverables,
    VariantCandidate,
    VariantSet,
    VideoAsset,
    VideoBundle,
    VideoScriptItem,
    VideoScriptPack,
)


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

    def _complete(self, provider: str, model: str, prompt: str, runtime_config: dict | None) -> tuple[str, str, float]:
        llm = self.providers.get(provider)
        runtime_config = runtime_config or {}
        response = llm.complete(
            prompt,
            model=model,
            api_base_url=runtime_config.get("api_base_url"),
            api_key=runtime_config.get("api_key"),
            extra=runtime_config.get("extra"),
        )
        return response.text, response.model_used, response.estimated_cost

    def run_intake(
        self,
        run_id: str,
        payload: dict,
        *,
        provider: str,
        model: str,
        runtime_config: dict | None = None,
    ) -> StageOutput:
        prompt = f"Normalize intake payload for creative generation: {payload}"
        summary, model_used, estimated_cost = self._complete(provider, model, prompt, runtime_config)
        intake = ProductIntake(
            product_name=payload.get("product_name", "unknown_product"),
            market=payload.get("market", "US"),
            locale=payload.get("locale", "en-US"),
            category_tags=payload.get("category_tags", []),
            business_context=payload.get("business_context", {}),
            manual_research_brief=payload.get("manual_research_brief", ""),
            url_references=payload.get("context", {}).get("url_references", []),
            sku_summary=payload.get("context", {}).get("input_assets", {}).get("sku_summary", []),
            image_references=payload.get("context", {}).get("input_assets", {}).get("sample_images", []),
            video_references=payload.get("context", {}).get("input_assets", {}).get("sample_videos", []),
        )
        normalized = {**intake.model_dump(), "llm_summary": summary}
        uri = self.media.write_text_artifact(run_id, "intake_summary.json", intake.model_dump_json(indent=2))
        return StageOutput(
            payload=normalized,
            model_used=model_used,
            estimated_cost=estimated_cost,
            artifacts=[{"type": "intake_summary", "uri": uri, "payload": normalized}],
        )

    def run_planning(
        self,
        run_id: str,
        intake: ProductIntake,
        *,
        gm_lessons: list[dict],
        enable_research: bool,
        provider: str,
        model: str,
        runtime_config: dict | None = None,
    ) -> StageOutput:
        mode = "online_research_enabled" if enable_research else "manual_research_only"
        prompt = (
            f"Build planning brief in {mode}. intake={intake.model_dump()} "
            f"gm_lessons={gm_lessons[:3]}"
        )
        summary, model_used, estimated_cost = self._complete(provider, model, prompt, runtime_config)
        value_props = intake.business_context.get("key_value_props", [])
        strategic_angles = value_props[:3] or [
            "time-saving daily workflow",
            "visible before/after proof",
            "risk-free practical messaging",
        ]
        constraints = intake.business_context.get("prohibited_claims", [])
        planning = PlanningBrief(
            strategic_angles=strategic_angles,
            audience_priorities=[intake.business_context.get("target_audience", "general pet owners")],
            positioning=intake.business_context.get("positioning", "practical premium utility"),
            constraints=constraints,
            gm_lessons=gm_lessons[:5],
        )
        output = {**planning.model_dump(), "planning_mode": mode, "llm_summary": summary}
        uri = self.media.write_text_artifact(run_id, "planning_brief.json", planning.model_dump_json(indent=2))
        return StageOutput(
            payload=output,
            model_used=model_used,
            estimated_cost=estimated_cost,
            artifacts=[{"type": "planning_brief", "uri": uri, "payload": output}],
        )

    def run_divergence(
        self,
        run_id: str,
        planning: PlanningBrief,
        *,
        variant_count: int,
        provider: str,
        model: str,
        runtime_config: dict | None = None,
    ) -> StageOutput:
        prompt = f"Generate diverse variants from planning: {planning.model_dump()}"
        summary, model_used, estimated_cost = self._complete(provider, model, prompt, runtime_config)
        variants = []
        for i in range(variant_count):
            angle = planning.strategic_angles[i % max(1, len(planning.strategic_angles))]
            variant_id = f"V{i + 1}"
            variants.append(
                VariantCandidate(
                    variant_id=variant_id,
                    angle=angle,
                    hook=f"{variant_id}: {angle} with fast daily benefit framing",
                    message=f"{variant_id}: practical result-first messaging for conversion objective.",
                )
            )
        variant_set = VariantSet(variants=variants)
        output = {**variant_set.model_dump(), "llm_summary": summary}
        uri = self.media.write_text_artifact(run_id, "variant_set.json", variant_set.model_dump_json(indent=2))
        return StageOutput(
            payload=output,
            model_used=model_used,
            estimated_cost=estimated_cost,
            artifacts=[{"type": "variant_set", "uri": uri, "payload": output}],
        )

    def run_copy_image_generation(
        self,
        run_id: str,
        variant_set: VariantSet,
        *,
        provider: str,
        model: str,
        runtime_config: dict | None = None,
    ) -> StageOutput:
        prompt = f"Generate copy and image prompts from variants: {variant_set.model_dump()}"
        _, model_used, estimated_cost = self._complete(provider, model, prompt, runtime_config)
        copies: list[CopyVariant] = []
        images: list[ImageAssetRef] = []
        for idx, item in enumerate(variant_set.variants):
            copies.append(
                CopyVariant(
                    variant_id=item.variant_id,
                    primary_text=f"{item.variant_id}: Cleaner routines in minutes, less stress for pet and owner.",
                    headline=f"{item.variant_id}: Daily Pet Care, Simplified",
                    description=f"Angle: {item.angle}",
                    call_to_action="Shop Now",
                )
            )
            image_uri = self.media.reserve_binary_artifact(run_id, f"copy_image_{idx + 1}.png")
            images.append(
                ImageAssetRef(
                    variant_id=item.variant_id,
                    uri=image_uri,
                    aspect_ratio="1:1",
                    prompt=f"Product hero image for {item.variant_id} with clean home and pet owner.",
                )
            )
        bundle = CopyImageBundle(copy_variants=copies, image_assets=images)
        uri = self.media.write_text_artifact(run_id, "copy_image_bundle.json", bundle.model_dump_json(indent=2))
        artifacts = [{"type": "copy_image_bundle", "uri": uri, "payload": bundle.model_dump()}]
        artifacts.extend({"type": "generated_image", "uri": img.uri, "payload": img.model_dump()} for img in images)
        return StageOutput(
            payload=bundle.model_dump(),
            model_used=model_used,
            estimated_cost=estimated_cost,
            artifacts=artifacts,
        )

    def run_video_scripting(
        self,
        run_id: str,
        variant_set: VariantSet,
        *,
        provider: str,
        model: str,
        runtime_config: dict | None = None,
    ) -> StageOutput:
        prompt = f"Generate video hooks and scripts: {variant_set.model_dump()}"
        _, model_used, estimated_cost = self._complete(provider, model, prompt, runtime_config)
        scripts = []
        for item in variant_set.variants:
            scripts.append(
                VideoScriptItem(
                    variant_id=item.variant_id,
                    hook=f"{item.variant_id}: Stop wasting 20 minutes on pet cleanup.",
                    script=(
                        "Hook scene -> problem scene -> solution demo -> before/after proof -> CTA. "
                        f"Variant message: {item.message}"
                    ),
                    shot_list=[
                        "messy problem shot",
                        "quick product usage shot",
                        "clean result shot",
                        "cta close shot",
                    ],
                )
            )
        pack = VideoScriptPack(scripts=scripts)
        uri = self.media.write_text_artifact(run_id, "video_scripts.json", pack.model_dump_json(indent=2))
        return StageOutput(
            payload=pack.model_dump(),
            model_used=model_used,
            estimated_cost=estimated_cost,
            artifacts=[{"type": "video_script_pack", "uri": uri, "payload": pack.model_dump()}],
        )

    def run_storyboard_image_generation(
        self,
        run_id: str,
        script_pack: VideoScriptPack,
        *,
        provider: str,
        model: str,
        runtime_config: dict | None = None,
    ) -> StageOutput:
        prompt = f"Create storyboard frames from scripts: {script_pack.model_dump()}"
        _, model_used, estimated_cost = self._complete(provider, model, prompt, runtime_config)
        frames: list[dict] = []
        artifacts: list[dict] = []
        for script in script_pack.scripts:
            for idx in range(3):
                frame_uri = self.media.reserve_binary_artifact(run_id, f"{script.variant_id}_storyboard_{idx + 1}.png")
                frame = {
                    "variant_id": script.variant_id,
                    "frame_id": f"{script.variant_id}_F{idx + 1}",
                    "prompt": f"Storyboard frame {idx + 1} for {script.variant_id}",
                    "image_uri": frame_uri,
                }
                frames.append(frame)
                artifacts.append({"type": "storyboard_frame", "uri": frame_uri, "payload": frame})
        output = {"frames": frames}
        uri = self.media.write_text_artifact(run_id, "storyboard_pack.json", str(output))
        artifacts.append({"type": "storyboard_pack", "uri": uri, "payload": output})
        return StageOutput(
            payload=output,
            model_used=model_used,
            estimated_cost=estimated_cost,
            artifacts=artifacts,
        )

    def run_video_generation(
        self,
        run_id: str,
        script_pack: VideoScriptPack,
        *,
        provider: str,
        model: str,
        runtime_config: dict | None = None,
    ) -> StageOutput:
        prompt = f"Generate videos from script pack: {script_pack.model_dump()}"
        _, model_used, estimated_cost = self._complete(provider, model, prompt, runtime_config)
        videos: list[VideoAsset] = []
        artifacts: list[dict] = []
        for script in script_pack.scripts:
            video_uri = self.media.reserve_binary_artifact(run_id, f"{script.variant_id}_sample.mp4")
            asset = VideoAsset(variant_id=script.variant_id, video_uri=video_uri, duration_seconds=15.0)
            videos.append(asset)
            artifacts.append({"type": "generated_video", "uri": video_uri, "payload": asset.model_dump()})
        bundle = VideoBundle(videos=videos)
        uri = self.media.write_text_artifact(run_id, "video_bundle.json", bundle.model_dump_json(indent=2))
        artifacts.append({"type": "video_bundle", "uri": uri, "payload": bundle.model_dump()})
        return StageOutput(
            payload=bundle.model_dump(),
            model_used=model_used,
            estimated_cost=estimated_cost,
            artifacts=artifacts,
        )

    def run_evaluation_selection(
        self,
        run_id: str,
        variant_set: VariantSet,
        copy_bundle: CopyImageBundle,
        script_pack: VideoScriptPack,
        video_bundle: VideoBundle,
        *,
        provider: str,
        model: str,
        runtime_config: dict | None = None,
    ) -> StageOutput:
        prompt = f"Evaluate and select best variants: {variant_set.model_dump()}"
        _, model_used, estimated_cost = self._complete(provider, model, prompt, runtime_config)
        copy_by_variant = {item.variant_id: item for item in copy_bundle.copy_variants}
        video_by_variant = {item.variant_id: item for item in video_bundle.videos}
        ranked: list[RankedVariant] = []
        for item in variant_set.variants:
            copy = copy_by_variant.get(item.variant_id)
            script = next((x for x in script_pack.scripts if x.variant_id == item.variant_id), None)
            hook_strength = min(100.0, 55.0 + len(item.hook) * 0.35)
            clarity = min(100.0, 50.0 + len((copy.primary_text if copy else "")) * 0.28)
            video_fit = 72.0 if video_by_variant.get(item.variant_id) else 40.0
            compliance = 90.0
            if script and ("guaranteed cure" in script.script.lower()):
                compliance = 15.0
            ai_naturalness = 86.0
            total = round(
                hook_strength * 0.28 + clarity * 0.22 + video_fit * 0.20 + compliance * 0.20 + ai_naturalness * 0.10,
                2,
            )
            level = ComplianceLevel.LOW if compliance >= 80 else ComplianceLevel.HIGH
            ranked.append(
                RankedVariant(
                    variant_id=item.variant_id,
                    total_score=total,
                    sub_scores={
                        "hook_strength": round(hook_strength, 2),
                        "clarity": round(clarity, 2),
                        "video_fit": round(video_fit, 2),
                        "compliance": round(compliance, 2),
                        "ai_naturalness": round(ai_naturalness, 2),
                    },
                    compliance_level=level,
                    reasons=[
                        f"angle={item.angle}",
                        "balanced copy/video quality" if total >= 60 else "needs stronger creative contrast",
                    ],
                )
            )
        ranked.sort(key=lambda x: x.total_score, reverse=True)
        top_k = ranked[:3]
        winner = top_k[0] if top_k else None
        winner_copy = copy_by_variant.get(winner.variant_id) if winner else None
        winner_images = [x for x in copy_bundle.image_assets if winner and x.variant_id == winner.variant_id]
        winner_video = video_by_variant.get(winner.variant_id) if winner else None
        selected = SelectedDeliverables(
            winner_variant_id=winner.variant_id if winner else "N/A",
            copy_variant=winner_copy,
            image_assets=winner_images,
            video_asset=winner_video,
            reasoning=winner.reasons if winner else ["no_winner_generated"],
        )
        scorecard = ScoreCard(
            sub_scores=ScoreBreakdown(
                attraction=winner.sub_scores.get("hook_strength", 50) if winner else 50,
                clarity=winner.sub_scores.get("clarity", 50) if winner else 50,
                brand_alignment=winner.sub_scores.get("video_fit", 50) if winner else 50,
                compliance=winner.sub_scores.get("compliance", 50) if winner else 50,
                ai_naturalness=winner.sub_scores.get("ai_naturalness", 50) if winner else 50,
            ),
            total_score=winner.total_score if winner else 50,
            risk_labels=[],
            explanation={"selection": "winner chosen by composite score across copy+video+compliance dimensions."},
            compliance_level=winner.compliance_level if winner else ComplianceLevel.MEDIUM,
            ai_artifact_score=winner.sub_scores.get("ai_naturalness", 50) if winner else 50,
        )
        forecast = ConversionForecast(
            score_0_100=scorecard.total_score,
            confidence_0_1=0.7 if scorecard.compliance_level == ComplianceLevel.LOW else 0.35,
            drivers=["hook_strength", "clarity", "video_fit", "compliance"],
            recommended_action="approve_for_launch_test" if scorecard.total_score >= 65 else "iterate_new_variants",
        )
        evaluation = EvaluationResult(
            ranked_variants=ranked,
            top_k=top_k,
            winner=winner,
            scorecard=scorecard,
            forecast=forecast,
        )
        payload = {
            "evaluation_result": evaluation.model_dump(),
            "selected_deliverables": selected.model_dump(),
            "variants": variant_set.model_dump(),
        }
        uri = self.media.write_text_artifact(run_id, "evaluation_selection.json", str(payload))
        return StageOutput(
            payload=payload,
            model_used=model_used,
            estimated_cost=estimated_cost,
            artifacts=[{"type": "evaluation_selection", "uri": uri, "payload": payload}],
            scorecard=scorecard,
            forecast=forecast,
        )

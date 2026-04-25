from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from app.providers.llm import (
    ImageGenRequest,
    MultimodalChatRequest,
    ProviderRegistry,
    VideoGenRequest,
    decode_placeholder_png,
)
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

    def _chat_complete(
        self,
        provider: str,
        model: str,
        prompt: str,
        runtime_config: dict | None,
        *,
        image_urls: list[str] | None = None,
        video_urls: list[str] | None = None,
    ) -> tuple[str, str, float]:
        llm = self.providers.get(provider)
        runtime = runtime_config or {}
        response = llm.chat_complete(
            MultimodalChatRequest(
                prompt=prompt,
                model=model,
                image_urls=image_urls or [],
                video_urls=video_urls or [],
            ),
            api_base_url=runtime.get("api_base_url"),
            api_key=runtime.get("api_key"),
            extra=runtime.get("extra"),
        )
        return response.text, response.model_used, response.estimated_cost

    def _generate_image(
        self,
        *,
        fallback_provider: str,
        fallback_model: str,
        prompt: str,
        size: str,
        runtime_config: dict | None,
    ):
        runtime = runtime_config or {}
        image_runtime = runtime.get("image") or {}
        provider_name = image_runtime.get("provider_name") or fallback_provider
        model_name = image_runtime.get("model_name") or fallback_model
        llm = self.providers.get(provider_name)
        result = llm.generate_image(
            ImageGenRequest(model=model_name, prompt=prompt, n=1, size=size),
            api_base_url=image_runtime.get("api_base_url") or runtime.get("api_base_url"),
            api_key=image_runtime.get("api_key") or runtime.get("api_key"),
            extra=image_runtime.get("extra") or runtime.get("extra"),
        )
        return result, provider_name, model_name

    def _generate_video(
        self,
        *,
        fallback_provider: str,
        fallback_model: str,
        prompt: str,
        size: str,
        resolution: str,
        duration_seconds: int,
        runtime_config: dict | None,
    ):
        runtime = runtime_config or {}
        video_runtime = runtime.get("video") or {}
        provider_name = video_runtime.get("provider_name") or fallback_provider
        model_name = video_runtime.get("model_name") or fallback_model
        llm = self.providers.get(provider_name)
        result = llm.generate_video(
            VideoGenRequest(
                model=model_name,
                prompt=prompt,
                size=size,
                resolution=resolution,
                n=1,
                duration_seconds=duration_seconds,
            ),
            api_base_url=video_runtime.get("api_base_url") or runtime.get("api_base_url"),
            api_key=video_runtime.get("api_key") or runtime.get("api_key"),
            extra=video_runtime.get("extra") or runtime.get("extra"),
        )
        return result, provider_name, model_name

    def _local_image_to_data_url(self, path_str: str) -> str | None:
        path = Path(path_str)
        if not path.exists() or not path.is_file():
            return None
        raw = path.read_bytes()
        if not raw:
            return None
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        encoded = base64.b64encode(raw).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    def _local_video_to_data_url(self, path_str: str, *, max_bytes: int = 20 * 1024 * 1024) -> str | None:
        path = Path(path_str)
        if not path.exists() or not path.is_file():
            return None
        raw = path.read_bytes()
        if not raw:
            return None
        if len(raw) > max_bytes:
            return None
        mime = mimetypes.guess_type(path.name)[0] or "video/mp4"
        if not mime.startswith("video/"):
            mime = "video/mp4"
        encoded = base64.b64encode(raw).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    def _reference_image_inputs(self, intake: ProductIntake | None) -> list[str]:
        if not intake:
            return []
        rows = intake.image_references or []
        inputs: list[str] = []
        for row in rows[:2]:
            if not isinstance(row, dict):
                continue
            uri = row.get("uri")
            if not isinstance(uri, str):
                continue
            data_url = self._local_image_to_data_url(uri)
            if data_url:
                inputs.append(data_url)
        return inputs

    def _reference_video_inputs(self, intake: ProductIntake | None) -> list[str]:
        if not intake:
            return []
        rows = intake.video_references or []
        inputs: list[str] = []
        for row in rows[:1]:
            if not isinstance(row, dict):
                continue
            uri = row.get("uri")
            if not isinstance(uri, str):
                continue
            data_url = self._local_video_to_data_url(uri)
            if data_url:
                inputs.append(data_url)
        return inputs

    def _download_url_bytes(self, url: str) -> bytes | None:
        try:
            with httpx.Client(timeout=90.0) as client:
                response = client.get(url)
                response.raise_for_status()
                return response.content
        except Exception:
            return None

    def _materialize_generated_image(self, generated_image) -> tuple[bytes, str]:
        if generated_image.b64_json:
            try:
                return base64.b64decode(generated_image.b64_json), "b64_json"
            except Exception:
                pass
        if generated_image.url:
            content = self._download_url_bytes(generated_image.url)
            if content:
                return content, "url"
        return decode_placeholder_png(), "placeholder"

    def _materialize_generated_video(self, generated_video) -> tuple[bytes, str]:
        if generated_video.b64_data:
            try:
                return base64.b64decode(generated_video.b64_data), "b64_data"
            except Exception:
                pass
        if generated_video.url:
            content = self._download_url_bytes(generated_video.url)
            if content:
                return content, "url"
        return b"", "placeholder"

    def run_intake(
        self,
        run_id: str,
        payload: dict,
        *,
        provider: str,
        model: str,
        runtime_config: dict | None = None,
    ) -> StageOutput:
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
        estimated_cost = 0.0
        model_used = model
        image_inputs = self._reference_image_inputs(intake)
        video_inputs = self._reference_video_inputs(intake)
        media_summary = ""
        if image_inputs or video_inputs:
            media_prompt = (
                "Analyze uploaded product media and output concise ad-useful facts: "
                "product appearance, material clues, fit/wearing method, usage scenes, motion cues, "
                "do-not-change constraints, and quality/compliance cautions."
            )
            try:
                media_summary, media_model_used, media_cost = self._chat_complete(
                    provider,
                    model,
                    media_prompt,
                    runtime_config,
                    image_urls=image_inputs,
                    video_urls=video_inputs,
                )
                model_used = media_model_used
                estimated_cost += media_cost
            except Exception as exc:
                if image_inputs:
                    try:
                        media_summary, media_model_used, media_cost = self._chat_complete(
                            provider,
                            model,
                            media_prompt,
                            runtime_config,
                            image_urls=image_inputs,
                        )
                        model_used = media_model_used
                        estimated_cost += media_cost
                    except Exception as image_exc:
                        media_summary = f"media_analysis_failed: {exc}; image_fallback_failed: {image_exc}"
                else:
                    media_summary = f"media_analysis_failed: {exc}"

        prompt = (
            f"Normalize intake payload for creative generation. payload={payload}. "
            f"asset_media_summary={media_summary}"
        )
        summary, model_used, llm_cost = self._chat_complete(provider, model, prompt, runtime_config)
        estimated_cost += llm_cost
        intake.asset_media_summary = media_summary
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
        summary, model_used, estimated_cost = self._chat_complete(provider, model, prompt, runtime_config)
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
        summary, model_used, estimated_cost = self._chat_complete(provider, model, prompt, runtime_config)
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
                    rationale=f"Test whether `{angle}` performs as the lead commercial promise for {variant_id}.",
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
        intake: ProductIntake | None,
        business_context: dict | None,
        creative_specs: dict | None,
        market: str,
        locale: str,
        provider: str,
        model: str,
        runtime_config: dict | None = None,
    ) -> StageOutput:
        business_context = business_context or {}
        creative_specs = creative_specs or {}
        image_size = str(creative_specs.get("image_size") or "1:1")
        resolution = str(creative_specs.get("resolution") or "720p")
        visual_summary = (
            intake.asset_media_summary.strip()
            if intake and intake.asset_media_summary
            else "No reference media analysis."
        )
        estimated_cost = 0.0
        text_model_used = model
        reference_inputs = self._reference_image_inputs(intake)
        if reference_inputs:
            vision_prompt = (
                "Analyze uploaded product sample image(s). Return concise product facts for ad generation: "
                "material, color, structure, wearing position, functional highlights, and what should remain consistent."
            )
            try:
                visual_summary, text_model_used, vision_cost = self._chat_complete(
                    provider,
                    model,
                    vision_prompt,
                    runtime_config,
                    image_urls=reference_inputs,
                )
                if intake and intake.asset_media_summary:
                    visual_summary = f"{intake.asset_media_summary}\n\nImage-focus details:\n{visual_summary}"
                estimated_cost += vision_cost
            except Exception as exc:
                visual_summary = f"reference_analysis_failed: {exc}"

        copy_prompt = (
            f"Generate concise Meta ad copy variants for US {locale}. "
            f"business_context={business_context}, product_visual_summary={visual_summary}, variants={variant_set.model_dump()}"
        )
        try:
            copy_hint, text_model_used, copy_cost = self._chat_complete(provider, model, copy_prompt, runtime_config)
            estimated_cost += copy_cost
        except Exception:
            copy_hint = "focus on practical outdoor use and comfort control."

        value_props = business_context.get("key_value_props", [])
        value_line = ", ".join(value_props[:3]) if value_props else "comfort control, durable material, daily reliability"
        price = business_context.get("price", "$35")
        audience = business_context.get("target_audience", "dog owners")
        cta = business_context.get("primary_cta", "Shop Now")

        copies: list[CopyVariant] = []
        images: list[ImageAssetRef] = []
        artifacts: list[dict] = []
        image_models_used: set[str] = set()

        for idx, item in enumerate(variant_set.variants):
            copies.append(
                CopyVariant(
                    variant_id=item.variant_id,
                    primary_text=(
                        f"{item.variant_id}: Built for {audience}. "
                        f"Outdoor-ready leash support with {value_line}. Price {price}."
                    ),
                    headline=f"{item.variant_id}: Outdoor Walks, Better Control",
                    description=f"Angle: {item.angle}. Hint: {copy_hint[:140]}",
                    call_to_action=cta,
                )
            )
            image_prompt = (
                f"Create a social media ad image for North American market ({market}, {locale}). "
                "Show a Labrador outdoors wearing/using the dog leash product naturally. "
                "Keep product details aligned with this summary: "
                f"{visual_summary}. "
                f"Style: realistic, brand-safe, no text overlay, sharp product visibility, conversion-oriented. "
                f"Use aspect ratio {image_size}, target resolution {resolution}."
            )
            image_uri = ""
            image_source = "placeholder"
            image_model = ""
            image_provider = ""
            error_text = None
            try:
                image_result, image_provider, image_model = self._generate_image(
                    fallback_provider=provider,
                    fallback_model=model,
                    prompt=image_prompt,
                    size=image_size,
                    runtime_config=runtime_config,
                )
                estimated_cost += image_result.estimated_cost
                image_models_used.add(image_result.model_used or image_model)
                selected = image_result.images[0] if image_result.images else None
                if selected:
                    image_bytes, image_source = self._materialize_generated_image(selected)
                else:
                    image_bytes, image_source = decode_placeholder_png(), "placeholder"
                image_uri = self.media.write_binary_artifact(run_id, f"copy_image_{idx + 1}.png", image_bytes)
            except Exception as exc:
                error_text = str(exc)
                image_uri = self.media.write_binary_artifact(run_id, f"copy_image_{idx + 1}.png", decode_placeholder_png())

            image_ref = ImageAssetRef(
                variant_id=item.variant_id,
                uri=image_uri,
                aspect_ratio=image_size,
                prompt=image_prompt,
            )
            image_payload = {
                **image_ref.model_dump(),
                "source": image_source,
                "image_provider": image_provider,
                "image_model": image_model,
                "error": error_text,
            }
            images.append(image_ref)
            artifacts.append(
                {
                    "type": "generated_image",
                    "uri": image_uri,
                    "payload": image_payload,
                }
            )

        bundle = CopyImageBundle(copy_variants=copies, image_assets=images)
        bundle_payload = {
            "copy_variants": [item.model_dump() for item in copies],
            "image_assets": [artifact["payload"] for artifact in artifacts if artifact["type"] == "generated_image"],
        }
        bundle_uri = self.media.write_text_artifact(run_id, "copy_image_bundle.json", bundle.model_dump_json(indent=2))
        artifacts.insert(0, {"type": "copy_image_bundle", "uri": bundle_uri, "payload": bundle_payload})
        model_used = f"text={text_model_used};image={','.join(sorted(m for m in image_models_used if m)) or 'placeholder'}"
        return StageOutput(
            payload=bundle_payload,
            model_used=model_used,
            estimated_cost=estimated_cost,
            artifacts=artifacts,
        )

    def run_video_scripting(
        self,
        run_id: str,
        variant_set: VariantSet,
        *,
        intake: ProductIntake | None,
        provider: str,
        model: str,
        runtime_config: dict | None = None,
    ) -> StageOutput:
        media_summary = ""
        if intake and intake.asset_media_summary:
            media_summary = intake.asset_media_summary
        prompt = (
            "Generate video hooks and scripts with the product context. "
            f"media_summary={media_summary}, variants={variant_set.model_dump()}"
        )
        _, model_used, estimated_cost = self._chat_complete(provider, model, prompt, runtime_config)
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
        _, model_used, estimated_cost = self._chat_complete(provider, model, prompt, runtime_config)
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
                    "source": "placeholder",
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
        creative_specs: dict | None,
        provider: str,
        model: str,
        runtime_config: dict | None = None,
    ) -> StageOutput:
        creative_specs = creative_specs or {}
        video_size = str(creative_specs.get("video_size") or "9:16")
        resolution = str(creative_specs.get("resolution") or "720p")
        duration_seconds = int(creative_specs.get("video_duration_seconds") or 8)
        prompt = f"Generate videos from script pack: {script_pack.model_dump()}"
        _, text_model_used, estimated_cost = self._chat_complete(provider, model, prompt, runtime_config)
        videos: list[VideoAsset] = []
        artifacts: list[dict] = []
        video_models_used: set[str] = set()
        for script in script_pack.scripts:
            video_prompt = (
                "Generate a short social ad video clip based on script. "
                f"Hook: {script.hook}. Script: {script.script}. Shots: {script.shot_list}. "
                f"Output should be brand-safe and product-forward, aspect ratio {video_size}, "
                f"target resolution {resolution}, duration {duration_seconds} seconds."
            )
            source = "placeholder"
            error_text = None
            model_used = ""
            provider_used = ""
            try:
                video_result, provider_used, model_used = self._generate_video(
                    fallback_provider=provider,
                    fallback_model=model,
                    prompt=video_prompt,
                    size=video_size,
                    resolution=resolution,
                    duration_seconds=duration_seconds,
                    runtime_config=runtime_config,
                )
                estimated_cost += video_result.estimated_cost
                selected = video_result.videos[0] if video_result.videos else None
                if selected:
                    video_bytes, source = self._materialize_generated_video(selected)
                else:
                    video_bytes, source = b"", "placeholder"
                video_uri = self.media.write_binary_artifact(run_id, f"{script.variant_id}_sample.mp4", video_bytes)
                video_models_used.add(video_result.model_used or model_used)
            except Exception as exc:
                error_text = str(exc)
                video_uri = self.media.reserve_binary_artifact(run_id, f"{script.variant_id}_sample.mp4")
            asset = VideoAsset(variant_id=script.variant_id, video_uri=video_uri, duration_seconds=float(duration_seconds))
            video_payload = {
                **asset.model_dump(),
                "source": source,
                "video_provider": provider_used,
                "video_model": model_used,
                "error": error_text,
                "prompt": video_prompt,
            }
            videos.append(VideoAsset.model_validate(video_payload))
            artifacts.append(
                {
                    "type": "generated_video",
                    "uri": video_uri,
                    "payload": video_payload,
                }
            )
        bundle = VideoBundle(videos=videos)
        bundle_payload = {"videos": [artifact["payload"] for artifact in artifacts if artifact["type"] == "generated_video"]}
        uri = self.media.write_text_artifact(run_id, "video_bundle.json", bundle.model_dump_json(indent=2))
        artifacts.append({"type": "video_bundle", "uri": uri, "payload": bundle_payload})
        final_model_used = f"text={text_model_used};video={','.join(sorted(m for m in video_models_used if m)) or 'placeholder'}"
        return StageOutput(
            payload=bundle_payload,
            model_used=final_model_used,
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
        _, model_used, estimated_cost = self._chat_complete(provider, model, prompt, runtime_config)
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
            compliance_risks: list[str] = []
            compliance_reasons: list[str] = []
            if script and ("guaranteed cure" in script.script.lower()):
                compliance = 15.0
                compliance_risks.append("legal_high_risk")
                compliance_reasons.append("Detected prohibited cure-style claim in script.")
            ai_naturalness = 86.0
            total = round(
                hook_strength * 0.28 + clarity * 0.22 + video_fit * 0.20 + compliance * 0.20 + ai_naturalness * 0.10,
                2,
            )
            level = ComplianceLevel.LOW if compliance >= 80 else ComplianceLevel.HIGH
            recommended_action = "approve_variant" if total >= 70 and level == ComplianceLevel.LOW else "manual_review" if level == ComplianceLevel.LOW else "request_regeneration"
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
                    compliance_risks=compliance_risks,
                    compliance_reasons=compliance_reasons or ["No major compliance issues detected."],
                    recommended_action=recommended_action,
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

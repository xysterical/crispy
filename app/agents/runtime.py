from __future__ import annotations

import base64
import json
import mimetypes
import re
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from app.providers.llm import (
    GeneratedVideo,
    ImageGenRequest,
    MultimodalChatRequest,
    ProviderRegistry,
    VideoGenRequest,
    decode_placeholder_png,
)
from app.providers.media import LocalMediaProvider
from app.services.marketplace_qa import (
    infer_visual_identity,
    inspect_marketplace_image,
    is_marketplace_main_image,
    normalize_platform_targets,
)
from app.services.visual_qa import inspect_visual_asset
from app.schemas.contracts import (
    ComplianceLevel,
    ConversionForecast,
    CopyImageBundle,
    CopyVariant,
    EvaluationResult,
    ImageAssetRef,
    PlanningBrief,
    ProductIntake,
    ProductVisualIdentity,
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
        extra = dict(runtime.get("extra") or {})
        for key in ("thinking_mode", "thinking_budget_tokens", "max_output_tokens", "request_timeout_seconds"):
            if runtime.get(key) is not None:
                extra[key] = runtime.get(key)
        streaming_enabled = bool(runtime.get("streaming_enabled") or extra.get("streaming_enabled"))
        trace_callback = runtime.get("trace_callback")
        if streaming_enabled:
            text_chunks: list[str] = []
            model_used = model
            estimated_cost = 0.0
            try:
                for event in llm.chat_complete_stream(
                    MultimodalChatRequest(
                        prompt=prompt,
                        model=model,
                        image_urls=image_urls or [],
                        video_urls=video_urls or [],
                    ),
                    api_base_url=runtime.get("api_base_url"),
                    api_key=runtime.get("api_key"),
                    extra=extra,
                ):
                    if event.type == "text_delta" and event.text:
                        text_chunks.append(event.text)
                        if trace_callback:
                            trace_callback("model_delta", event.text, {"event_type": event.type})
                    elif event.type == "reasoning_summary" and event.text and trace_callback:
                        trace_callback("reasoning_summary", event.text, {"event_type": event.type})
                    elif event.type == "completed":
                        model_used = str(event.payload.get("model") or model_used)
                        estimated_cost = float(event.payload.get("estimated_cost") or 0.0)
                        if event.payload.get("text") and not text_chunks:
                            text_chunks.append(str(event.payload["text"]))
                        if trace_callback:
                            trace_callback("model_stream_completed", "Model stream completed.", event.payload)
                return "".join(text_chunks), model_used, estimated_cost
            except Exception:
                if trace_callback:
                    trace_callback("model_stream_fallback", "Streaming failed; falling back to non-streaming call.", {})
        response = llm.chat_complete(
            MultimodalChatRequest(
                prompt=prompt,
                model=model,
                image_urls=image_urls or [],
                video_urls=video_urls or [],
            ),
            api_base_url=runtime.get("api_base_url"),
            api_key=runtime.get("api_key"),
            extra=extra,
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
        reference_image_urls: list[str] | None = None,
        mode: str = "generate",
        input_fidelity: str | None = None,
    ):
        runtime = runtime_config or {}
        image_runtime = runtime.get("image") or {}
        provider_name = image_runtime.get("provider_name") or fallback_provider
        model_name = image_runtime.get("model_name") or fallback_model
        llm = self.providers.get(provider_name)
        result = llm.generate_image(
            ImageGenRequest(
                model=model_name,
                prompt=prompt,
                n=1,
                size=size,
                reference_image_urls=reference_image_urls or [],
                mode=mode,
                input_fidelity=input_fidelity,
            ),
            api_base_url=image_runtime.get("api_base_url") or runtime.get("api_base_url"),
            api_key=image_runtime.get("api_key") or runtime.get("api_key"),
            extra=image_runtime.get("extra") or runtime.get("extra"),
        )
        return result, provider_name, model_name

    def _generate_video_submit_only(
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
        video_runtime = dict(runtime.get("video") or {})
        video_extra = dict(video_runtime.get("extra") or runtime.get("extra") or {})
        video_extra["submit_only"] = True
        video_runtime["extra"] = video_extra
        submit_runtime = {**runtime, "video": video_runtime}
        return self._generate_video(
            fallback_provider=fallback_provider,
            fallback_model=fallback_model,
            prompt=prompt,
            size=size,
            resolution=resolution,
            duration_seconds=duration_seconds,
            runtime_config=submit_runtime,
        )

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

    def _marketplace_reference_inputs(self, intake: ProductIntake | None, max_inputs: int = 4) -> tuple[list[str], list[dict]]:
        if not intake:
            return [], []
        identity = intake.visual_identity.model_dump() if hasattr(intake.visual_identity, "model_dump") else dict(intake.visual_identity or {})
        candidates: list[dict] = []
        for uri in identity.get("best_reference_images") or []:
            candidates.append({"uri": uri, "source": "visual_identity_image"})
        for uri in identity.get("best_reference_frames") or []:
            candidates.append({"uri": uri, "source": "visual_identity_video_frame"})
        for row in intake.image_references or []:
            if isinstance(row, dict) and row.get("uri"):
                candidates.append({"uri": row["uri"], "source": "uploaded_image"})
        for row in intake.video_references or []:
            if not isinstance(row, dict):
                continue
            for uri in row.get("frame_placeholders") or row.get("frame_uris") or []:
                candidates.append({"uri": uri, "source": "uploaded_video_frame", "source_video": row.get("uri")})

        data_urls: list[str] = []
        manifest: list[dict] = []
        seen: set[str] = set()
        for item in candidates:
            uri = item.get("uri")
            if not isinstance(uri, str) or not uri or uri in seen:
                continue
            seen.add(uri)
            data_url = self._local_image_to_data_url(uri)
            if not data_url:
                continue
            data_urls.append(data_url)
            manifest.append({**item, "input_index": len(manifest) + 1})
            if len(data_urls) >= max_inputs:
                break
        return data_urls, manifest

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

    def _artifact_has_payload(self, uri: str | None, min_bytes: int = 1024) -> bool:
        if not uri:
            return False
        path = Path(uri)
        return path.exists() and path.is_file() and path.stat().st_size > min_bytes

    def _leash_physical_constraints(self) -> str:
        return (
            "Hard visual constraints for dog leash realism: the leash must be one continuous visible strap or rope "
            "from the handler's hand to the dog collar or harness clip; the clip must be fully attached to a collar "
            "or harness D-ring; do not show a floating clip, missing strap segment, disconnected leash, broken leash, "
            "impossible attachment point, extra duplicate leash, malformed dog anatomy, or cropped detail that hides "
            "the connection logic."
        )

    def _business_strategy_system_prompt(self, agent_role: str) -> str:
        return (
            f"You are acting as {agent_role} in a commercial advertising creative pipeline. "
            "Operate like a senior growth strategist, not a generic copywriter. Preserve product truths, "
            "state assumptions, separate commercial hypothesis from compliance-sensitive claims, and produce "
            "handoff-ready decisions that another agent can audit. Never hide uncertainty."
        )

    def _business_strategy_handoff(self, *, stage: str, decisions: list[str], risks: list[str], review_questions: list[str]) -> dict:
        return {
            "stage": stage,
            "decisions": decisions,
            "risks": risks,
            "review_questions": review_questions,
            "handoff_standard": "commercial-pilot-v2",
        }

    def _local_media_qa(self, *, asset_type: str, uri: str | None, payload: dict | None = None, expected_ratio: str | None = None) -> dict:
        return inspect_visual_asset(asset_type=asset_type, uri=uri, payload=payload or {}, expected_ratio=expected_ratio)

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
            "Normalize this product intake for ad creative generation in concise, execution-ready bullets. "
            f"product_name={intake.product_name}; market={intake.market}; locale={intake.locale}; "
            f"category_tags={intake.category_tags}; business_context={intake.business_context}; "
            f"manual_research_brief={intake.manual_research_brief}; "
            f"uploaded_assets={{'sku_count': {len(intake.sku_summary)}, 'image_count': {len(intake.image_references)}, "
            f"'video_count': {len(intake.video_references)}}}; asset_media_summary={media_summary[:1200]}"
        )
        summary, model_used, llm_cost = self._chat_complete(provider, model, prompt, runtime_config)
        estimated_cost += llm_cost
        intake.asset_media_summary = media_summary
        intake.visual_identity = ProductVisualIdentity.model_validate(
            infer_visual_identity(
                product_name=intake.product_name,
                category_tags=intake.category_tags,
                media_summary=media_summary,
                image_references=intake.image_references,
                video_references=intake.video_references,
            )
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
        gm_policy: dict | None = None,
        enable_research: bool,
        provider: str,
        model: str,
        runtime_config: dict | None = None,
    ) -> StageOutput:
        mode = "online_research_enabled" if enable_research else "manual_research_only"
        gm_policy = gm_policy or {}
        policy_excerpt = gm_policy.get("stage_guidance") or {}
        prompt = (
            f"{self._business_strategy_system_prompt('Planning Agent')} "
            f"Build planning brief in {mode}. intake={intake.model_dump()} "
            f"gm_lessons={gm_lessons[:3]}. gm_policy={policy_excerpt}. Return concise strategy, constraints, hypotheses, risk boundaries, "
            "and reviewer decision questions."
        )
        summary, model_used, estimated_cost = self._chat_complete(provider, model, prompt, runtime_config)
        value_props = intake.business_context.get("key_value_props", [])
        strategic_angles = (gm_policy.get("angle_priorities") or [])[:3] or value_props[:3] or [
            "time-saving daily workflow",
            "visible before/after proof",
            "risk-free practical messaging",
        ]
        constraints = list(intake.business_context.get("prohibited_claims", []))
        constraints.extend(str(item) for item in (gm_policy.get("hard_constraints") or [])[:5])
        constraints = list(dict.fromkeys(item for item in constraints if str(item).strip()))
        shop_thesis = gm_policy.get("shop_thesis") or {}
        planning = PlanningBrief(
            strategic_angles=strategic_angles,
            audience_priorities=[intake.business_context.get("target_audience", "general pet owners")],
            positioning=shop_thesis.get("positioning") or intake.business_context.get("positioning", "practical premium utility"),
            constraints=constraints,
            gm_lessons=gm_lessons[:5],
        )
        strategy_handoff = self._business_strategy_handoff(
            stage="planning",
            decisions=[
                f"positioning={planning.positioning}",
                f"primary_audience={planning.audience_priorities[0] if planning.audience_priorities else 'general'}",
                f"angle_count={len(planning.strategic_angles)}",
            ],
            risks=[str(item) for item in constraints] or ["No explicit prohibited claims supplied."],
            review_questions=[
                "Are the listed product truths sufficient for generation?",
                "Should any claim boundary be tightened before variants are generated?",
                "Which angle should be deprioritized for this market or channel?",
            ],
        )
        output = {
            **planning.model_dump(),
            "planning_mode": mode,
            "llm_summary": summary,
            "strategy_handoff": strategy_handoff,
            "commercial_strategy": {
                "audience": planning.audience_priorities,
                "positioning": planning.positioning,
                "angle_portfolio": planning.strategic_angles,
                "claim_boundaries": planning.constraints,
                "memory_applied_count": len(gm_lessons[:5]),
                "active_gm_policy": {
                    "policy_version_ids": gm_policy.get("policy_version_ids", []),
                    "applied_scopes": gm_policy.get("applied_scopes", []),
                },
            },
            "active_gm_policy": gm_policy,
        }
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
        gm_policy: dict | None = None,
        provider: str,
        model: str,
        runtime_config: dict | None = None,
    ) -> StageOutput:
        gm_policy = gm_policy or {}
        policy_excerpt = gm_policy.get("stage_guidance") or {}
        prompt = (
            f"{self._business_strategy_system_prompt('Variant Strategy Agent')} "
            f"Generate diverse variants from planning: {planning.model_dump()}. "
            f"gm_policy={policy_excerpt}. "
            "Each variant must test a distinct commercial hypothesis with non-overlapping hook logic."
        )
        summary, model_used, estimated_cost = self._chat_complete(provider, model, prompt, runtime_config)
        variants = []
        preferred_angles = (gm_policy.get("angle_priorities") or [])[: max(1, variant_count)]
        for i in range(variant_count):
            angle_pool = preferred_angles or planning.strategic_angles
            angle = angle_pool[i % max(1, len(angle_pool))]
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
        experiment_matrix = [
            {
                "variant_id": item.variant_id,
                "test_axis": item.angle,
                "hypothesis": item.message,
                "success_signal": "Higher qualified click-through or stronger reviewer preference than adjacent variants.",
                "kill_condition": "Weak product relevance, unsupported claim, or visual concept cannot show the product truthfully.",
            }
            for item in variants
        ]
        output = {
            **variant_set.model_dump(),
            "llm_summary": summary,
            "experiment_matrix": experiment_matrix,
            "active_gm_policy": gm_policy,
            "strategy_handoff": self._business_strategy_handoff(
                stage="divergence",
                decisions=[f"created {len(variants)} variant hypotheses", "kept variants bound to distinct test axes"],
                risks=["Variants are heuristic until reviewed against generated media."],
                review_questions=["Are the variants commercially distinct?", "Should any variant be killed before paid generation?"],
            ),
        }
        uri = self.media.write_text_artifact(run_id, "variant_set.json", variant_set.model_dump_json(indent=2))
        return StageOutput(
            payload=output,
            model_used=model_used,
            estimated_cost=estimated_cost,
            artifacts=[{"type": "variant_set", "uri": uri, "payload": output}],
        )

    def _run_marketplace_main_image_generation(
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
        platform_targets = normalize_platform_targets(creative_specs)
        export_size_px = int(creative_specs.get("export_size_px") or 2000)
        image_size = str(creative_specs.get("image_size") or "1:1")
        visual_summary = intake.asset_media_summary.strip() if intake and intake.asset_media_summary else "No reference media analysis."
        visual_identity = (
            intake.visual_identity.model_dump()
            if intake and hasattr(intake.visual_identity, "model_dump")
            else dict((intake.visual_identity if intake else {}) or {})
        )
        reference_inputs, reference_manifest = self._marketplace_reference_inputs(intake, max_inputs=4)
        roles = [
            {
                "image_role": "compliance_master",
                "style": (
                    "strict marketplace master photo, exact product only, pure #FFFFFF background, no props, no model, "
                    "no text overlay, no watermark, product centered and filling 65-90% of the square frame"
                ),
            },
            {
                "image_role": "premium_white",
                "style": (
                    "premium white-background catalog photo with improved material texture, clean edge refinement, "
                    "natural product-contained lighting, color correction, and no scene background"
                ),
            },
        ]
        estimated_cost = 0.0
        copies: list[CopyVariant] = []
        images: list[ImageAssetRef] = []
        artifacts: list[dict] = []
        image_models_used: set[str] = set()
        audience = business_context.get("target_audience", "marketplace shoppers")
        cta = business_context.get("primary_cta", "View Product")
        product_name = intake.product_name if intake else str(business_context.get("product_name") or "the product")

        for idx, item in enumerate(variant_set.variants):
            role = roles[idx % len(roles)]
            image_role = role["image_role"]
            copies.append(
                CopyVariant(
                    variant_id=item.variant_id,
                    primary_text=(
                        f"{item.variant_id}: Marketplace main image candidate for {product_name}; "
                        f"role={image_role}; audience={audience}."
                    ),
                    headline=f"{product_name} Main Image",
                    description=f"White-background product-photo candidate for {', '.join(platform_targets)}.",
                    call_to_action=cta,
                )
            )
            prompt = (
                "Edit the uploaded source product media into a source-accurate marketplace main image. "
                "Preserve exact product shape, color, logo/text, material, proportions, and included parts from the references. "
                "Do not invent accessories, packaging, labels, claims, props, people, animals, hands, lifestyle scenes, or text overlays. "
                f"Product visual identity: {json.dumps(visual_identity, ensure_ascii=False)[:2200]}. "
                f"Media summary: {visual_summary[:1600]}. "
                f"Role: {image_role}; style requirements: {role['style']}. "
                f"Output: square {export_size_px}x{export_size_px}px master, pure white background, marketplace-ready for {platform_targets}. "
                "If source media is low quality, improve lighting, material clarity, edge quality, and color balance while preserving product truth."
            )
            image_uri = ""
            image_source = "placeholder"
            image_model = ""
            image_provider = ""
            error_text = None
            provider_errors: list[dict] = []
            asset_suffix = str((runtime_config or {}).get("asset_name_suffix") or "")
            force_regenerate = bool((runtime_config or {}).get("force_regenerate"))
            image_filename = f"marketplace_{item.variant_id}_{image_role}{asset_suffix}.png"
            existing_image_path = self.media.settings.assets_dir / run_id / image_filename
            try:
                if not force_regenerate and existing_image_path.exists() and existing_image_path.stat().st_size > 1024:
                    image_uri = str(existing_image_path)
                    image_source = "reused_existing"
                else:
                    image_result, image_provider, image_model = self._generate_image(
                        fallback_provider=provider,
                        fallback_model=model,
                        prompt=prompt,
                        size=image_size,
                        runtime_config=runtime_config,
                        reference_image_urls=reference_inputs,
                        mode="edit" if reference_inputs else "generate",
                        input_fidelity="high" if reference_inputs else None,
                    )
                    estimated_cost += image_result.estimated_cost
                    image_models_used.add(image_result.model_used or image_model)
                    selected = image_result.images[0] if image_result.images else None
                    if selected:
                        image_bytes, image_source = self._materialize_generated_image(selected)
                    else:
                        image_bytes, image_source = decode_placeholder_png(), "placeholder"
                    image_uri = self.media.write_binary_artifact(run_id, image_filename, image_bytes)
            except Exception as exc:
                error_text = str(exc)
                provider_errors = getattr(exc, "errors", []) or []
                image_uri = self.media.write_binary_artifact(run_id, image_filename, decode_placeholder_png())

            image_ref = ImageAssetRef(
                variant_id=item.variant_id,
                uri=image_uri,
                aspect_ratio=image_size,
                prompt=prompt,
            )
            image_payload = {
                **image_ref.model_dump(),
                "asset_goal": "marketplace_main_image",
                "image_role": image_role,
                "platform_targets": platform_targets,
                "export_size_px": export_size_px,
                "source": image_source,
                "image_provider": image_provider,
                "image_model": image_model,
                "error": error_text,
                "provider_errors": provider_errors,
                "reference_source_count": len(reference_inputs),
                "reference_manifest": reference_manifest,
                "visual_identity": visual_identity,
            }
            image_payload["visual_qa"] = self._local_media_qa(
                asset_type="image",
                uri=image_uri,
                payload=image_payload,
                expected_ratio=image_size,
            )
            image_payload["marketplace_qa"] = inspect_marketplace_image(
                uri=image_uri,
                payload=image_payload,
                creative_specs=creative_specs,
                visual_identity=visual_identity,
            )
            image_payload["platform_readiness"] = image_payload["marketplace_qa"].get("platform_readiness", {})
            image_payload["export_ready"] = bool(image_payload["marketplace_qa"].get("export_ready"))
            images.append(image_ref)
            artifacts.append({"type": "generated_image", "uri": image_uri, "payload": image_payload})

        bundle = CopyImageBundle(copy_variants=copies, image_assets=images)
        bundle_payload = {
            "asset_goal": "marketplace_main_image",
            "copy_variants": [item.model_dump() for item in copies],
            "image_assets": [artifact["payload"] for artifact in artifacts if artifact["type"] == "generated_image"],
            "visual_identity": visual_identity,
            "reference_manifest": reference_manifest,
            "strategy_handoff": self._business_strategy_handoff(
                stage="copy_image_generation",
                decisions=[
                    f"generated marketplace main-image candidates for {len(copies)} variants",
                    "used source media references when available",
                    f"target_platforms={','.join(platform_targets)}",
                ],
                risks=["Provider reference-edit support may vary; marketplace QA and source-product review are required before export."],
                review_questions=[
                    "Does the generated product match the phone reference exactly?",
                    "Is the background pure white without prop/model leakage?",
                    "Which candidate is ready for marketplace export?",
                ],
            ),
        }
        bundle_uri = self.media.write_text_artifact(run_id, "marketplace_main_image_bundle.json", bundle.model_dump_json(indent=2))
        artifacts.insert(0, {"type": "copy_image_bundle", "uri": bundle_uri, "payload": bundle_payload})
        model_used = f"text={model};image={','.join(sorted(m for m in image_models_used if m)) or 'placeholder'}"
        return StageOutput(
            payload=bundle_payload,
            model_used=model_used,
            estimated_cost=estimated_cost,
            artifacts=artifacts,
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
        if is_marketplace_main_image(creative_specs):
            return self._run_marketplace_main_image_generation(
                run_id,
                variant_set,
                intake=intake,
                business_context=business_context,
                creative_specs=creative_specs,
                market=market,
                locale=locale,
                provider=provider,
                model=model,
                runtime_config=runtime_config,
            )

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
            f"{self._business_strategy_system_prompt('Copy Image Agent')} "
            f"Generate concise Meta ad copy variants for US {locale}. "
            f"business_context={business_context}, product_visual_summary={visual_summary}, variants={variant_set.model_dump()}. "
            "Keep copy specific, conversion-oriented, and claim-safe. Do not invent certifications or guarantees."
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
                f"Use aspect ratio {image_size}, target resolution {resolution}. "
                "Visual QA gate: product must be clearly inspectable, physically plausible, not malformed, and not a generic pet stock image."
            )
            image_uri = ""
            image_source = "placeholder"
            image_model = ""
            image_provider = ""
            error_text = None
            provider_errors: list[dict] = []
            asset_suffix = str((runtime_config or {}).get("asset_name_suffix") or "")
            force_regenerate = bool((runtime_config or {}).get("force_regenerate"))
            image_filename = f"copy_image_{idx + 1}{asset_suffix}.png"
            existing_image_path = self.media.settings.assets_dir / run_id / image_filename
            try:
                if not force_regenerate and existing_image_path.exists() and existing_image_path.stat().st_size > 1024:
                    image_uri = str(existing_image_path)
                    image_source = "reused_existing"
                else:
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
                    image_uri = self.media.write_binary_artifact(run_id, image_filename, image_bytes)
            except Exception as exc:
                error_text = str(exc)
                provider_errors = getattr(exc, "errors", []) or []
                image_uri = self.media.write_binary_artifact(run_id, image_filename, decode_placeholder_png())

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
                "provider_errors": provider_errors,
            }
            image_payload["visual_qa"] = self._local_media_qa(
                asset_type="image",
                uri=image_uri,
                payload=image_payload,
                expected_ratio=image_size,
            )
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
            "strategy_handoff": self._business_strategy_handoff(
                stage="copy_image_generation",
                decisions=[f"generated copy/image candidates for {len(copies)} variants", "kept no-text-overlay image prompts"],
                risks=["Image provider may still introduce malformed product details; visual QA and human review required."],
                review_questions=["Is the product visibly correct?", "Does copy avoid unsupported claims?", "Which image has strongest product-forward composition?"],
            ),
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
        business_context: dict | None = None,
        provider: str,
        model: str,
        creative_specs: dict | None = None,
        pipeline_mode: str | None = None,
        runtime_config: dict | None = None,
    ) -> StageOutput:
        business_context = business_context or {}
        creative_specs = creative_specs or {}
        is_tiktok_shop = pipeline_mode == "tiktok_shop_video"
        tiktok_style = str(creative_specs.get("tiktok_video_style") or "ugc_demo")
        media_summary = ""
        if intake and intake.asset_media_summary:
            media_summary = intake.asset_media_summary
        product_name = intake.product_name if intake else str(business_context.get("product_name") or "the product")
        value_props_raw = business_context.get("key_value_props") or business_context.get("value_props") or []
        if isinstance(value_props_raw, str):
            value_props = [value_props_raw]
        else:
            value_props = [str(item) for item in value_props_raw if str(item).strip()]
        if not value_props:
            value_props = ["reflective visibility", "comfortable control", "outdoor-ready durability"]
        audience_raw = business_context.get("target_audience") or business_context.get("audience") or []
        if isinstance(audience_raw, str):
            audience = audience_raw
        elif audience_raw:
            audience = ", ".join(str(item) for item in audience_raw[:3])
        else:
            audience = "urban dog owners and weekend trail walkers"
        cta = str(business_context.get("primary_cta") or "Shop Now")
        prompt = (
            f"{self._business_strategy_system_prompt('Video Script Agent')} "
            "Generate video hooks and scripts with the product context. "
            f"product={product_name}, audience={audience}, value_props={value_props}, "
            f"media_summary={media_summary}, variants={variant_set.model_dump()}. "
            "Make every shot filmable, product-specific, and constrained by physical continuity."
        )
        _, model_used, estimated_cost = self._chat_complete(provider, model, prompt, runtime_config)
        scripts = []
        for item in variant_set.variants:
            primary_value = value_props[(len(scripts)) % len(value_props)]
            hook_base = item.hook or item.angle or primary_value
            tiktok_payload = None
            if is_tiktok_shop:
                opening_hook = f"POV: your {product_name} solves this in seconds"
                proof_points = [primary_value, item.message][:2]
                if tiktok_style == "direct_response_ad":
                    opening_hook = f"Stop scrolling if you need {primary_value}"
                    cta_intensity = "strong"
                elif tiktok_style == "shop_account_content":
                    opening_hook = f"Packing one small upgrade from our shop: {product_name}"
                    cta_intensity = "soft"
                else:
                    cta_intensity = "medium"
                tiktok_payload = {
                    "style": tiktok_style,
                    "opening_hook": opening_hook,
                    "on_screen_text": [
                        opening_hook,
                        f"Proof: {primary_value}",
                        cta,
                    ],
                    "voiceover_lines": [
                        opening_hook,
                        f"Here is how {product_name} helps with {primary_value}.",
                        f"If this fits your routine, {cta}.",
                    ],
                    "shot_timing": [
                        {
                            "start": 0,
                            "end": 2,
                            "visual": "fast vertical product reveal in a realistic use scene",
                            "text_overlay": opening_hook,
                            "intent": "thumb_stop",
                        },
                        {
                            "start": 2,
                            "end": 8,
                            "visual": "close product demo with the key proof point visible",
                            "text_overlay": f"Proof: {primary_value}",
                            "intent": "proof",
                        },
                        {
                            "start": 8,
                            "end": float(creative_specs.get("video_duration_seconds") or 12),
                            "visual": "product-forward end frame with clear next step",
                            "text_overlay": cta,
                            "intent": "cta",
                        },
                    ],
                    "product_proof_points": proof_points,
                    "cta": cta,
                    "compliance_notes": [
                        "Do not invent certifications, discounts, platform trends, or unsupported performance claims.",
                        f"CTA intensity: {cta_intensity}.",
                    ],
                }
            scripts.append(
                VideoScriptItem(
                    variant_id=item.variant_id,
                    hook=f"{item.variant_id}: Safer-feeling walks start with {primary_value}.",
                    script=(
                        f"Open on a real dog walk with {product_name} clipped to a collar or harness. "
                        f"Show the leash handle, quick clip, and reflective detail in close-up. "
                        f"Cut to {audience} using it on a sidewalk or trail while keeping the dog close without exaggerated claims. "
                        f"End with {cta}. Variant hook: {hook_base}. Variant message: {item.message}"
                    ),
                    shot_list=[
                        "vertical hook shot of a medium or large dog starting a walk with the leash visible",
                        "close-up of padded handle, nylon strap, and quick clip in the owner's hand",
                        "outdoor walking demo showing calm control and reflective detail without safety guarantees",
                        f"product-forward CTA end frame: {cta}",
                    ],
                    tiktok=tiktok_payload,
                )
            )
        pack = VideoScriptPack(scripts=scripts)
        payload = {
            **pack.model_dump(),
            "strategy_handoff": self._business_strategy_handoff(
                stage="video_scripting",
                decisions=[f"generated scripts for {len(scripts)} variants", "required close-up product handling and physical continuity"],
                risks=["Script quality still depends on storyboard and video provider following continuity constraints."],
                review_questions=["Does each hook feel native to TikTok?", "Can every shot be generated without breaking product logic?"],
            ),
        }
        uri = self.media.write_text_artifact(run_id, "video_scripts.json", pack.model_dump_json(indent=2))
        return StageOutput(
            payload=payload,
            model_used=model_used,
            estimated_cost=estimated_cost,
            artifacts=[{"type": "video_script_pack", "uri": uri, "payload": payload}],
        )

    def run_storyboard_image_generation(
        self,
        run_id: str,
        script_pack: VideoScriptPack,
        *,
        provider: str,
        model: str,
        creative_specs: dict | None = None,
        runtime_config: dict | None = None,
    ) -> StageOutput:
        creative_specs = creative_specs or {}
        image_size = str(creative_specs.get("video_size") or creative_specs.get("image_size") or "9:16")
        prompt = (
            f"{self._business_strategy_system_prompt('Storyboard Agent')} "
            f"Create storyboard frames from scripts: {script_pack.model_dump()}. "
            "Treat storyboard as the visual QA plan before video generation: continuity, object logic, product visibility."
        )
        estimated_cost = 0.0
        error_text = None
        try:
            _, model_used, estimated_cost = self._chat_complete(provider, model, prompt, runtime_config)
        except Exception as exc:
            model_used = f"{provider}/{model}:storyboard_text_unavailable"
            error_text = str(exc)
        frames: list[dict] = []
        artifacts: list[dict] = []
        for script in script_pack.scripts:
            for idx in range(3):
                shot = script.shot_list[idx] if idx < len(script.shot_list) else script.hook
                tiktok_details = script.tiktok.model_dump() if script.tiktok else {}
                style_line = (
                    f"TikTok style: {tiktok_details.get('style')}. "
                    f"Opening hook: {tiktok_details.get('opening_hook')}. "
                    if tiktok_details
                    else ""
                )
                frame_prompt = (
                    f"Create a realistic vertical storyboard frame for a TikTok dog leash ad. "
                    f"Variant {script.variant_id}. Shot: {shot}. Hook: {script.hook}. "
                    f"{style_line}"
                    "Use a clean previsualization style suitable for human review before video generation. "
                    "No text overlay. Product-forward composition. "
                    f"{self._leash_physical_constraints()}"
                )
                source = "placeholder"
                image_provider = ""
                image_model = ""
                frame_error = error_text
                provider_errors: list[dict] = []
                try:
                    image_result, image_provider, image_model = self._generate_image(
                        fallback_provider=provider,
                        fallback_model=model,
                        prompt=frame_prompt,
                        size=image_size,
                        runtime_config=runtime_config,
                    )
                    estimated_cost += image_result.estimated_cost
                    selected = image_result.images[0] if image_result.images else None
                    if selected:
                        frame_bytes, source = self._materialize_generated_image(selected)
                    else:
                        frame_bytes, source = decode_placeholder_png(), "placeholder"
                    asset_suffix = str((runtime_config or {}).get("asset_name_suffix") or "")
                    frame_uri = self.media.write_binary_artifact(
                        run_id,
                        f"{script.variant_id}_storyboard_{idx + 1}{asset_suffix}.png",
                        frame_bytes,
                    )
                    if source != "placeholder":
                        frame_error = None
                except Exception as exc:
                    frame_error = str(exc)
                    provider_errors = getattr(exc, "errors", []) or []
                    frame_uri = self.media.write_binary_artifact(
                        run_id,
                        f"{script.variant_id}_storyboard_{idx + 1}{str((runtime_config or {}).get('asset_name_suffix') or '')}.png",
                        decode_placeholder_png(),
                    )
                frame = {
                    "variant_id": script.variant_id,
                    "frame_id": f"{script.variant_id}_F{idx + 1}",
                    "prompt": frame_prompt,
                    "image_uri": frame_uri,
                    "source": source,
                    "image_provider": image_provider,
                    "image_model": image_model,
                    "error": frame_error,
                    "provider_errors": provider_errors,
                }
                frame["visual_qa"] = self._local_media_qa(
                    asset_type="storyboard_frame",
                    uri=frame_uri,
                    payload=frame,
                    expected_ratio=image_size,
                )
                frames.append(frame)
                artifacts.append({"type": "storyboard_frame", "uri": frame_uri, "payload": frame})
        output = {
            "frames": frames,
            "strategy_handoff": self._business_strategy_handoff(
                stage="storyboard_image_generation",
                decisions=[f"created {len(frames)} storyboard frames", "each frame prompt repeats product continuity constraints"],
                risks=["Storyboard image QA is basic; complex physics still requires reviewer/model inspection."],
                review_questions=["Do storyboard frames preserve product continuity?", "Should any variant be regenerated before video generation?"],
            ),
        }
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
        on_video_asset=None,
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
            tiktok_details = script.tiktok.model_dump() if script.tiktok else {}
            tiktok_line = ""
            if tiktok_details:
                tiktok_line = (
                    f"TikTok Shop style={tiktok_details.get('style')}; "
                    f"opening_hook={tiktok_details.get('opening_hook')}; "
                    f"on_screen_text={tiktok_details.get('on_screen_text')}; "
                    f"cta={tiktok_details.get('cta')}. "
                )
            video_prompt = (
                "Generate a short social ad video clip based on script. "
                f"Hook: {script.hook}. Script: {script.script}. Shots: {script.shot_list}. "
                f"{tiktok_line}"
                f"Output should be brand-safe and product-forward, aspect ratio {video_size}, "
                f"target resolution {resolution}, duration {duration_seconds} seconds. "
                f"{self._leash_physical_constraints()} Reject any frame where the leash is visually broken, "
                "partially missing, or attached without a logical continuous strap."
            )
            source = "placeholder"
            error_text = None
            model_used = ""
            provider_used = ""
            generation_status = None
            external_task_id = None
            result_url = None
            raw_response: dict = {}
            provider_errors: list[dict] = []
            video_uri = ""
            asset_suffix = str((runtime_config or {}).get("asset_name_suffix") or "")
            force_regenerate = bool((runtime_config or {}).get("force_regenerate"))
            video_filename = f"{script.variant_id}_sample{asset_suffix}.mp4"
            existing_video_path = self.media.settings.assets_dir / run_id / video_filename
            try:
                if not force_regenerate and self._artifact_has_payload(str(existing_video_path)):
                    video_uri = str(existing_video_path)
                    source = "reused_existing"
                    generation_status = "completed"
                else:
                    video_result, provider_used, model_used = self._generate_video_submit_only(
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
                    external_task_id = video_result.task_id
                    generation_status = video_result.status
                    raw_response = video_result.raw_response or {}
                    if selected:
                        external_task_id = selected.task_id or external_task_id
                        generation_status = selected.status or generation_status
                        result_url = selected.url
                        raw_response = selected.raw_response or raw_response
                    if selected and (selected.url or selected.b64_data):
                        video_bytes, source = self._materialize_generated_video(selected)
                        video_uri = self.media.write_binary_artifact(run_id, video_filename, video_bytes)
                    elif external_task_id:
                        source = "external_task_pending"
                        video_uri = self.media.reserve_binary_artifact(run_id, video_filename)
                    else:
                        video_uri = self.media.write_binary_artifact(run_id, video_filename, b"")
                    video_models_used.add(video_result.model_used or model_used)
            except Exception as exc:
                error_text = str(exc)
                provider_errors = getattr(exc, "errors", []) or []
                video_uri = self.media.reserve_binary_artifact(run_id, video_filename)
            asset = VideoAsset(variant_id=script.variant_id, video_uri=video_uri, duration_seconds=float(duration_seconds))
            video_payload = {
                **asset.model_dump(),
                "source": source,
                "video_provider": provider_used,
                "video_model": model_used,
                "error": error_text,
                "prompt": video_prompt,
                "external_task_id": external_task_id,
                "generation_status": generation_status,
                "result_url": result_url,
                "raw_response": raw_response,
                "provider_errors": provider_errors,
                "quality_constraints": {
                    "leash_connection_required": True,
                    "reject_missing_or_floating_clip": True,
                    "reject_disconnected_or_cropped_leash": True,
                },
            }
            video_payload["visual_qa"] = self._local_media_qa(
                asset_type="video",
                uri=video_uri,
                payload=video_payload,
                expected_ratio=video_size,
            )
            videos.append(VideoAsset.model_validate(video_payload))
            artifacts.append(
                {
                    "type": "generated_video",
                    "uri": video_uri,
                    "payload": video_payload,
                }
            )
            if on_video_asset:
                on_video_asset(video_payload)
        bundle = VideoBundle(videos=videos)
        bundle_payload = {
            "videos": [artifact["payload"] for artifact in artifacts if artifact["type"] == "generated_video"],
            "strategy_handoff": self._business_strategy_handoff(
                stage="video_generation",
                decisions=[f"submitted/generated video assets for {len(videos)} variants", "stored provider task metadata for recovery"],
                risks=["Pending async videos require refresh before final visual QA can pass."],
                review_questions=["Did the completed video preserve product logic?", "Should broken continuity variants be regenerated?"],
            ),
        }
        uri = self.media.write_text_artifact(run_id, "video_bundle.json", bundle.model_dump_json(indent=2))
        artifacts.append({"type": "video_bundle", "uri": uri, "payload": bundle_payload})
        final_model_used = f"text={text_model_used};video={','.join(sorted(m for m in video_models_used if m)) or 'placeholder'}"
        return StageOutput(
            payload=bundle_payload,
            model_used=final_model_used,
            estimated_cost=estimated_cost,
            artifacts=artifacts,
        )

    def run_visual_quality_assessment(
        self,
        run_id: str,
        variant_set: VariantSet,
        *,
        copy_images: dict | None = None,
        video_scripts: dict | None = None,
        storyboards: dict | None = None,
        videos: dict | None = None,
        intake: dict | None = None,
        business_context: dict | None = None,
        creative_specs: dict | None = None,
        gm_policy: dict | None = None,
        provider: str,
        model: str,
        runtime_config: dict | None = None,
    ) -> StageOutput:
        copy_images = copy_images or {}
        video_scripts = video_scripts or {}
        storyboards = storyboards or {}
        videos = videos or {}
        intake = intake or {}
        business_context = business_context or {}
        creative_specs = creative_specs or {}
        gm_policy = gm_policy or {}
        marketplace_goal = is_marketplace_main_image(creative_specs)
        visual_identity = dict(intake.get("visual_identity") or {}) if isinstance(intake, dict) else {}

        def _asset_items(payload: dict, key: str) -> list[dict]:
            rows = payload.get(key) or []
            return [dict(item) for item in rows if isinstance(item, dict)]

        asset_rows: list[dict] = []
        for image in _asset_items(copy_images, "image_assets"):
            asset_rows.append({"asset_type": "image", **image})
        for frame in _asset_items(storyboards, "frames"):
            asset_rows.append({"asset_type": "storyboard_frame", **frame, "uri": frame.get("image_uri")})
        for video in _asset_items(videos, "videos"):
            asset_rows.append({"asset_type": "video", **video, "uri": video.get("video_uri")})

        scripts_by_variant = {item.get("variant_id"): item for item in _asset_items(video_scripts, "scripts")}
        reports: list[dict] = []
        summaries: list[dict] = []
        model_image_inputs: list[str] = []
        model_video_inputs: list[str] = []
        model_media_manifest: list[dict] = []

        def _media_url_for_model(asset: dict, *, media_type: str) -> str | None:
            uri = asset.get("uri")
            if not isinstance(uri, str) or not uri:
                return None
            if uri.startswith(("http://", "https://", "data:")):
                return uri
            if media_type == "video":
                return self._local_video_to_data_url(uri)
            return self._local_image_to_data_url(uri)

        max_model_images = int(((runtime_config or {}).get("extra") or {}).get("visual_qa_max_model_images") or 12)
        max_model_videos = int(((runtime_config or {}).get("extra") or {}).get("visual_qa_max_model_videos") or 4)

        for variant in variant_set.variants:
            variant_assets = [item for item in asset_rows if item.get("variant_id") == variant.variant_id]
            asset_reports: list[dict] = []
            blocking_issues: list[str] = []
            platform_readiness: dict[str, str] = {}
            score_values: list[float] = []
            pending = False
            warn = False
            export_ready_assets = 0
            for asset in variant_assets:
                asset_type = str(asset.get("asset_type") or "")
                expected_ratio = None
                if asset_type in {"image", "storyboard_frame"}:
                    expected_ratio = asset.get("aspect_ratio") or (creative_specs.get("image_size") if isinstance(creative_specs, dict) else None)
                qa = asset.get("visual_qa")
                if not isinstance(qa, dict):
                    qa = self._local_media_qa(
                        asset_type=asset_type,
                        uri=asset.get("uri"),
                        payload=asset,
                        expected_ratio=expected_ratio,
                    )
                flags = qa.get("flags") or []
                status = str(qa.get("status") or "warn")
                if isinstance(qa.get("score"), (int, float)):
                    score_values.append(float(qa["score"]))
                if status == "fail":
                    blocking_issues.extend(str(flag) for flag in flags)
                marketplace_qa = asset.get("marketplace_qa")
                if marketplace_goal and asset_type == "image":
                    if not isinstance(marketplace_qa, dict):
                        marketplace_qa = inspect_marketplace_image(
                            uri=asset.get("uri"),
                            payload=asset,
                            creative_specs=creative_specs,
                            visual_identity=visual_identity,
                        )
                        asset["marketplace_qa"] = marketplace_qa
                    market_status = str(marketplace_qa.get("status") or "warn")
                    market_flags = [str(flag) for flag in (marketplace_qa.get("flags") or [])]
                    flags = sorted(set([*flags, *market_flags]))
                    if isinstance(marketplace_qa.get("score"), (int, float)):
                        score_values.append(float(marketplace_qa["score"]))
                    if market_status == "fail":
                        blocking_issues.extend(market_flags or ["marketplace_qa_failed"])
                    if market_status == "warn":
                        warn = True
                    if marketplace_qa.get("export_ready"):
                        export_ready_assets += 1
                    for platform, readiness in (marketplace_qa.get("platform_readiness") or {}).items():
                        current = platform_readiness.get(platform)
                        if current == "fail" or readiness == "fail":
                            platform_readiness[platform] = "fail"
                        elif current == "warn" or readiness == "warn":
                            platform_readiness[platform] = "warn"
                        else:
                            platform_readiness[platform] = str(readiness)
                if "visual_qa_video_processing" in flags or str(asset.get("generation_status") or "").lower() in {"submitted", "queued", "pending", "processing", "running"}:
                    pending = True
                if status == "warn":
                    warn = True
                if "visual_qa_needs_frame_review" in flags:
                    warn = True
                if asset_type in {"image", "storyboard_frame"} and len(model_image_inputs) < max_model_images:
                    media_url = _media_url_for_model(asset, media_type="image")
                    if media_url:
                        model_image_inputs.append(media_url)
                        model_media_manifest.append(
                            {
                                "input_index": len(model_media_manifest) + 1,
                                "modality": "image",
                                "variant_id": variant.variant_id,
                                "asset_type": asset_type,
                                "uri": asset.get("uri"),
                            }
                        )
                if asset_type == "video" and len(model_video_inputs) < max_model_videos:
                    media_url = _media_url_for_model(asset, media_type="video")
                    if media_url:
                        model_video_inputs.append(media_url)
                        model_media_manifest.append(
                            {
                                "input_index": len(model_media_manifest) + 1,
                                "modality": "video",
                                "variant_id": variant.variant_id,
                                "asset_type": asset_type,
                                "uri": asset.get("uri"),
                                "generation_status": asset.get("generation_status"),
                            }
                        )
                asset_reports.append(
                    {
                        "asset_type": asset_type,
                        "uri": asset.get("uri"),
                        "generation_status": asset.get("generation_status"),
                        "external_task_id": asset.get("external_task_id"),
                        "qa_status": status,
                        "visual_score": qa.get("score"),
                        "flags": flags,
                        "checks": qa.get("checks") or [],
                        "marketplace_qa": marketplace_qa if marketplace_goal and asset_type == "image" else None,
                    }
                )

            if not variant_assets:
                blocking_issues.append("visual_qa_no_generated_assets")
            visual_score = min(score_values) if score_values else 0.0
            if pending:
                qa_status = "pending"
                recommended_action = "wait_for_asset"
            elif blocking_issues:
                qa_status = "fail"
                recommended_action = "request_regeneration"
            elif marketplace_goal and variant_assets and export_ready_assets <= 0:
                qa_status = "warn"
                recommended_action = "manual_review"
            elif warn or visual_score < 80:
                qa_status = "warn"
                recommended_action = "manual_review"
            else:
                qa_status = "pass"
                recommended_action = "pass_to_evaluation"
            export_ready = marketplace_goal and not pending and not blocking_issues and bool(platform_readiness) and all(
                value == "pass" for value in platform_readiness.values()
            )

            script = scripts_by_variant.get(variant.variant_id) or {}
            report = {
                "variant_id": variant.variant_id,
                "angle": variant.angle,
                "hook": variant.hook,
                "qa_status": qa_status,
                "visual_score": round(visual_score, 2),
                "asset_reports": asset_reports,
                "blocking_issues": sorted(set(blocking_issues)),
                "review_notes": (
                    f"{variant.variant_id} visual QA {qa_status}; "
                    f"{len(asset_reports)} assets checked; action={recommended_action}."
                ),
                "recommended_action": recommended_action,
                "platform_readiness": platform_readiness,
                "export_ready": export_ready,
                "script_hook": script.get("hook"),
            }
            reports.append(report)
            summaries.append(
                {
                    "variant_id": variant.variant_id,
                    "qa_status": qa_status,
                    "visual_score": report["visual_score"],
                    "blocking_issue_count": len(report["blocking_issues"]),
                    "recommended_action": recommended_action,
                    "issues": report["blocking_issues"],
                    "platform_readiness": platform_readiness,
                    "export_ready": export_ready,
                }
            )

        prompt = (
            f"{self._business_strategy_system_prompt('Visual QA Agent')} "
            "Review these structured visual QA records for ad-candidate risk. "
            "Focus on product fidelity, physical plausibility, leash continuity if relevant, channel fit, and whether any candidate should be blocked before evaluation. "
            "Return concise operator notes; do not choose the final winner.\n"
            f"intake_facts={json.dumps(intake, ensure_ascii=False)[:3000]}\n"
            f"business_context={json.dumps(business_context, ensure_ascii=False)[:1800]}\n"
            f"qa_records={json.dumps(summaries, ensure_ascii=False)[:5000]}\n"
            f"attached_media_manifest={json.dumps(model_media_manifest, ensure_ascii=False)[:3000]}\n"
            f"gm_policy={json.dumps(gm_policy.get('stage_guidance') or {}, ensure_ascii=False)[:2000]}"
        )
        model_summary = ""
        model_used = model
        estimated_cost = 0.0
        try:
            model_summary, model_used, estimated_cost = self._chat_complete(
                provider,
                model,
                prompt,
                runtime_config,
                image_urls=model_image_inputs,
                video_urls=model_video_inputs,
            )
        except Exception as exc:
            model_summary = f"model_review_unavailable: {str(exc)[:240]}"

        payload = {
            "reports": reports,
            "variant_summaries": summaries,
            "model_summary": model_summary,
            "model_media_inputs": {
                "image_count": len(model_image_inputs),
                "video_count": len(model_video_inputs),
                "manifest": model_media_manifest,
            },
            "active_gm_policy": gm_policy,
            "strategy_handoff": self._business_strategy_handoff(
                stage="visual_quality_assessment",
                decisions=[f"checked visual quality for {len(summaries)} variants", "blocked or downgraded incomplete and visually risky assets before evaluation"],
                risks=["Large videos may be skipped from model media input and require async refresh or frame sampling."],
                review_questions=["Which variants need human frame review?", "Should failed assets be regenerated before ranking?"],
            ),
        }
        uri = self.media.write_text_artifact(run_id, "visual_quality_assessment.json", json.dumps(payload, ensure_ascii=False, indent=2))
        return StageOutput(
            payload=payload,
            model_used=model_used,
            estimated_cost=estimated_cost,
            artifacts=[{"type": "visual_quality_report", "uri": uri, "payload": payload}],
        )

    def run_evaluation_selection(
        self,
        run_id: str,
        variant_set: VariantSet,
        copy_bundle: CopyImageBundle,
        script_pack: VideoScriptPack,
        video_bundle: VideoBundle,
        visual_quality: dict | None = None,
        *,
        provider: str,
        model: str,
        creative_specs: dict | None = None,
        pipeline_mode: str | None = None,
        gm_policy: dict | None = None,
        runtime_config: dict | None = None,
    ) -> StageOutput:
        creative_specs = creative_specs or {}
        gm_policy = gm_policy or {}
        is_tiktok_shop = pipeline_mode == "tiktok_shop_video"
        tiktok_style = str(creative_specs.get("tiktok_video_style") or "ugc_demo")
        prompt = (
            f"Evaluate and select best variants: {variant_set.model_dump()}. "
            f"gm_policy={gm_policy.get('stage_guidance') or {}}"
        )
        _, model_used, estimated_cost = self._chat_complete(provider, model, prompt, runtime_config)
        copy_by_variant = {item.variant_id: item for item in copy_bundle.copy_variants}
        video_by_variant = {item.variant_id: item for item in video_bundle.videos}
        image_by_variant = {item.variant_id: item for item in copy_bundle.image_assets}
        visual_quality = visual_quality or {}
        visual_summary_by_variant = {
            item.get("variant_id"): item
            for item in (visual_quality.get("variant_summaries") or [])
            if isinstance(item, dict) and item.get("variant_id")
        }
        ranked: list[RankedVariant] = []
        for item in variant_set.variants:
            copy = copy_by_variant.get(item.variant_id)
            script = next((x for x in script_pack.scripts if x.variant_id == item.variant_id), None)
            image = image_by_variant.get(item.variant_id)
            video = video_by_variant.get(item.variant_id)
            has_valid_image = self._artifact_has_payload(image.uri if image else None)
            has_valid_video = self._artifact_has_payload(video.video_uri if video else None)
            visual_qas: list[dict] = []
            if image:
                visual_qas.append(
                    self._local_media_qa(
                        asset_type="image",
                        uri=image.uri,
                        payload=image.model_dump(),
                        expected_ratio=image.aspect_ratio,
                    )
                )
            if video:
                visual_qas.append(
                    self._local_media_qa(
                        asset_type="video",
                        uri=video.video_uri,
                        payload=video.model_dump(),
                    )
                )
            visual_qa_score = max([qa.get("score", 0.0) for qa in visual_qas] or [0.0])
            visual_qa_flags = sorted({flag for qa in visual_qas for flag in (qa.get("flags") or [])})
            qa_summary = visual_summary_by_variant.get(item.variant_id) or {}
            if isinstance(qa_summary.get("visual_score"), (int, float)):
                visual_qa_score = min(visual_qa_score if visual_qas else 100.0, float(qa_summary["visual_score"]))
            qa_status = str(qa_summary.get("qa_status") or "")
            qa_recommended_action = str(qa_summary.get("recommended_action") or "")
            qa_issues = [str(issue) for issue in (qa_summary.get("issues") or [])]
            visual_qa_flags = sorted(set([*visual_qa_flags, *qa_issues]))
            hook_strength = min(100.0, 55.0 + len(item.hook) * 0.35)
            clarity = min(100.0, 50.0 + len((copy.primary_text if copy else "")) * 0.28)
            generation_fit = 88.0 if has_valid_video else 82.0 if has_valid_image else 25.0
            generation_fit = min(generation_fit, visual_qa_score)
            compliance = 90.0
            compliance_risks: list[str] = []
            compliance_reasons: list[str] = []
            if script and ("guaranteed cure" in script.script.lower()):
                compliance = 15.0
                compliance_risks.append("legal_high_risk")
                compliance_reasons.append("Detected prohibited cure-style claim in script.")
            ai_naturalness = 86.0
            total = round(
                hook_strength * 0.24 + clarity * 0.20 + generation_fit * 0.26 + compliance * 0.20 + ai_naturalness * 0.10,
                2,
            )
            level = ComplianceLevel.LOW if compliance >= 80 else ComplianceLevel.HIGH
            if qa_status == "pending" or qa_recommended_action == "wait_for_asset":
                recommended_action = "manual_review"
                generation_fit = min(generation_fit, 35.0)
            elif qa_status == "fail" or qa_recommended_action == "request_regeneration":
                recommended_action = "request_regeneration"
                generation_fit = min(generation_fit, 25.0)
                total = min(total, 49.0)
            elif not (has_valid_image or has_valid_video):
                recommended_action = "request_regeneration"
            elif any(flag in visual_qa_flags for flag in {"visual_qa_placeholder", "visual_qa_empty_video", "visual_qa_decode_error"}):
                recommended_action = "request_regeneration"
            else:
                recommended_action = "approve_variant" if total >= 70 and level == ComplianceLevel.LOW else "manual_review" if level == ComplianceLevel.LOW else "request_regeneration"
            total = round(
                hook_strength * 0.24 + clarity * 0.20 + generation_fit * 0.26 + compliance * 0.20 + ai_naturalness * 0.10,
                2,
            )
            if recommended_action == "request_regeneration":
                total = min(total, 49.0)
            tiktok_scores: dict[str, float] = {}
            if is_tiktok_shop:
                script_details = script.tiktok if script else None
                has_tiktok_script = script_details is not None
                on_screen_text_count = len(script_details.on_screen_text) if script_details else 0
                shot_count = len(script_details.shot_timing) if script_details else 0
                thumb_stop_power = min(100.0, hook_strength + (8 if has_tiktok_script else 0))
                product_clarity = min(100.0, generation_fit + (6 if shot_count >= 2 else 0))
                purchase_intent = min(100.0, clarity + (10 if tiktok_style == "direct_response_ad" else 4))
                native_tiktok_feel = min(100.0, ai_naturalness + (8 if tiktok_style in {"ugc_demo", "shop_account_content"} else 2))
                watch_through_potential = min(100.0, 62.0 + shot_count * 6 + on_screen_text_count * 2)
                claim_safety = compliance
                generation_feasibility = generation_fit
                tiktok_scores = {
                    "thumb_stop_power": round(thumb_stop_power, 2),
                    "product_clarity": round(product_clarity, 2),
                    "purchase_intent": round(purchase_intent, 2),
                    "native_tiktok_feel": round(native_tiktok_feel, 2),
                    "watch_through_potential": round(watch_through_potential, 2),
                    "claim_safety": round(claim_safety, 2),
                    "generation_feasibility": round(generation_feasibility, 2),
                }
                if tiktok_style == "direct_response_ad":
                    total = round(
                        thumb_stop_power * 0.18
                        + product_clarity * 0.18
                        + purchase_intent * 0.22
                        + native_tiktok_feel * 0.10
                        + watch_through_potential * 0.10
                        + claim_safety * 0.12
                        + generation_feasibility * 0.10,
                        2,
                    )
                elif tiktok_style == "shop_account_content":
                    total = round(
                        thumb_stop_power * 0.14
                        + product_clarity * 0.14
                        + purchase_intent * 0.12
                        + native_tiktok_feel * 0.20
                        + watch_through_potential * 0.18
                        + claim_safety * 0.12
                        + generation_feasibility * 0.10,
                        2,
                    )
                else:
                    total = round(
                        thumb_stop_power * 0.15
                        + product_clarity * 0.20
                        + purchase_intent * 0.15
                        + native_tiktok_feel * 0.18
                        + watch_through_potential * 0.10
                        + claim_safety * 0.12
                        + generation_feasibility * 0.10,
                        2,
                    )
                if recommended_action == "request_regeneration":
                    total = min(total, 49.0)
            ranked.append(
                RankedVariant(
                    variant_id=item.variant_id,
                    total_score=total,
                    sub_scores={
                        "hook_strength": round(hook_strength, 2),
                        "clarity": round(clarity, 2),
                        "generation_fit": round(generation_fit, 2),
                        "visual_qa": round(visual_qa_score, 2),
                        "compliance": round(compliance, 2),
                        "ai_naturalness": round(ai_naturalness, 2),
                        **tiktok_scores,
                    },
                    compliance_level=level,
                    reasons=[
                        f"angle={item.angle}",
                        "valid generated media available" if has_valid_image or has_valid_video else "generated media missing or placeholder",
                        f"visual_qa_flags={','.join(visual_qa_flags) if visual_qa_flags else 'none'}",
                        f"visual_qa_agent_status={qa_status or 'not_run'}",
                    ],
                    compliance_risks=[*compliance_risks, *visual_qa_flags],
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
                brand_alignment=winner.sub_scores.get("generation_fit", 50) if winner else 50,
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
            drivers=["hook_strength", "clarity", "generation_fit", "compliance"],
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
            "active_gm_policy": gm_policy,
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

    def run_shop_profile_analysis(
        self,
        store_url: str,
        description: str,
        *,
        provider: str,
        model: str,
        runtime_config: dict | None = None,
        tavily_api_key: str | None = None,
        firecrawl_api_key: str | None = None,
    ) -> dict:
        """Phase 1: Analyze a store's own positioning, SEO, and product catalog using real web search."""
        from app.search import FirecrawlClient, TavilyClient

        store_content = ""
        tavily_results: dict = {}
        search_errors: list[str] = []

        if firecrawl_api_key:
            try:
                fc = FirecrawlClient(api_key=firecrawl_api_key)
                result = fc.scrape(store_url)
                store_content = result.markdown[:8000]
            except Exception as exc:
                search_errors.append(f"firecrawl_scrape: {exc}")

        if tavily_api_key:
            try:
                tv = TavilyClient(api_key=tavily_api_key)
                search_query = f"{description or store_url} brand positioning reviews target audience"
                tavily_results = tv.search_raw(search_query, max_results=5)
            except Exception as exc:
                search_errors.append(f"tavily_search: {exc}")

        prompt_parts = [
            f"{self._business_strategy_system_prompt('Shop Analyst')}",
            f"Research this store: {store_url}",
            f"Operator description: {description or 'None provided'}.",
        ]
        if store_content:
            prompt_parts.append(
                f"SCRAPED STORE CONTENT (from Firecrawl):\n{store_content}\n---"
            )
        if tavily_results:
            prompt_parts.append(
                f"WEB SEARCH RESULTS (from Tavily): {json.dumps(tavily_results, indent=2)}\n---"
            )
        if search_errors:
            prompt_parts.append(
                f"Search errors (partial data): {'; '.join(search_errors)}"
            )
        prompt_parts.append(
            "Produce a STRUCTURED JSON profile: positioning (one-line), target_audience (string), "
            "price_tier (budget/mid/premium), product_categories (list), unique_selling_points (list), "
            "seo_keywords (list of 5-10 search terms), content_gaps (list), "
            "brand_voice (tone and style description). "
            "Return ONLY valid JSON, no markdown wrapping."
        )
        prompt = "\n".join(prompt_parts)

        summary, model_used, estimated_cost = self._chat_complete(provider, model, prompt, runtime_config)
        try:
            profile = json.loads(summary)
        except json.JSONDecodeError:
            match = re.search(r'\{[\s\S]*\}', summary)
            profile = json.loads(match.group(0)) if match else {"raw_response": summary}

        return {
            "profile": profile,
            "model_used": model_used,
            "estimated_cost": estimated_cost,
            "search_errors": search_errors if search_errors else None,
        }

    def run_competitor_analysis(
        self,
        store_url: str,
        description: str,
        store_profile: dict,
        *,
        provider: str,
        model: str,
        runtime_config: dict | None = None,
        tavily_api_key: str | None = None,
        firecrawl_api_key: str | None = None,
    ) -> dict:
        """Phase 2: Analyze competitors based on store profile using real web search."""
        from app.search import FirecrawlClient, TavilyClient

        search_errors: list[str] = []
        competitor_search_results: dict = {}
        competitor_pages: list[str] = []

        if tavily_api_key:
            try:
                tv = TavilyClient(api_key=tavily_api_key)
                positioning = store_profile.get("positioning", description)
                categories = store_profile.get("product_categories", [])
                cat_str = ", ".join(categories[:3]) if categories else ""
                query = f"competitors similar to {positioning} {cat_str} online store"
                competitor_search_results = tv.search_raw(query, max_results=5)
                for r in (competitor_search_results.get("results") or []):
                    url = r.get("url", "")
                    if url and url != store_url:
                        competitor_pages.append(url)
            except Exception as exc:
                search_errors.append(f"tavily_competitor_search: {exc}")

        competitor_content: list[str] = []
        if firecrawl_api_key and competitor_pages:
            try:
                fc = FirecrawlClient(api_key=firecrawl_api_key)
                for comp_url in competitor_pages[:3]:
                    try:
                        result = fc.scrape(comp_url)
                        competitor_content.append(
                            f"URL: {comp_url}\nTITLE: {result.title}\n{result.markdown[:4000]}"
                        )
                    except Exception:
                        competitor_content.append(f"URL: {comp_url}\n[Scrape failed]")
            except Exception as exc:
                search_errors.append(f"firecrawl_competitor: {exc}")

        prompt_parts = [
            f"{self._business_strategy_system_prompt('Shop Analyst')}",
            f"Store profile: {json.dumps(store_profile)}",
            f"Store URL: {store_url}",
            f"Operator notes: {description or 'None provided'}.",
        ]
        if competitor_search_results:
            prompt_parts.append(
                f"COMPETITOR SEARCH RESULTS: {json.dumps(competitor_search_results, indent=2)}\n---"
            )
        if competitor_content:
            prompt_parts.append(
                "COMPETITOR PAGE CONTENT:\n" + "\n---\n".join(competitor_content)
            )
        if search_errors:
            prompt_parts.append(f"Search errors (partial data): {'; '.join(search_errors)}")
        prompt_parts.append(
            "Identify 3-5 comparable competitors. For each: positioning, creative/ad style patterns, "
            "pricing approach, differentiation opportunities. "
            "Return Markdown with: ## Competitive Landscape Overview, ## Competitor N (name, URL, analysis), "
            "## Differentiation Opportunities, ## Recommended Creative Angles."
        )
        prompt = "\n".join(prompt_parts)

        summary, model_used, estimated_cost = self._chat_complete(provider, model, prompt, runtime_config)
        return {
            "report": summary,
            "model_used": model_used,
            "estimated_cost": estimated_cost,
            "search_errors": search_errors if search_errors else None,
        }

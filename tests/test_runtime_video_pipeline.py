from __future__ import annotations

import base64
from pathlib import Path

import pytest

from app.agents.runtime import AgentsRuntime
from app.providers.llm import GeneratedVideo, VideoGenResult
from app.schemas.contracts import PlanningBrief, ProductIntake, VariantCandidate, VariantSet, VideoScriptItem, VideoScriptPack


class _FakeVideoProvider:
    def __init__(self) -> None:
        self.last_request = None
        self.last_extra = None

    def generate_video(self, request, *, api_base_url=None, api_key=None, extra=None):
        self.last_request = request
        self.last_extra = extra
        return VideoGenResult(
            model_used=request.model,
            videos=[GeneratedVideo(task_id="task-video-001", status="submitted")],
            task_id="task-video-001",
            status="submitted",
            raw_response={"status": "submitted"},
        )


class _FakeCompletedVideoProvider:
    def __init__(self) -> None:
        self.requests = []

    def generate_video(self, request, *, api_base_url=None, api_key=None, extra=None):
        self.requests.append(request)
        payload = base64.b64encode((f"video-{len(self.requests)}".encode("utf-8") * 256)).decode("ascii")
        return VideoGenResult(
            model_used=request.model,
            videos=[GeneratedVideo(b64_data=payload, status="completed", raw_response={"last_frame_url": f"https://example.com/last-{len(self.requests)}.png"})],
            status="completed",
            raw_response={"status": "completed"},
        )


class _FakeCompletedVideoProviderWithoutLastFrameUrl:
    def __init__(self) -> None:
        self.requests = []

    def generate_video(self, request, *, api_base_url=None, api_key=None, extra=None):
        self.requests.append(request)
        payload = base64.b64encode((f"video-{len(self.requests)}".encode("utf-8") * 256)).decode("ascii")
        return VideoGenResult(
            model_used=request.model,
            videos=[GeneratedVideo(b64_data=payload, status="completed", raw_response={})],
            status="completed",
            raw_response={"status": "completed"},
        )


class _FakeRegistry:
    def __init__(self, provider) -> None:
        self.provider = provider

    def get(self, _provider_name: str):
        return self.provider


def test_video_generation_traces_selected_provider_decision():
    runtime = AgentsRuntime()
    fake_provider = _FakeVideoProvider()
    runtime.providers = _FakeRegistry(fake_provider)
    events = []

    result, provider_name, model_name = runtime._generate_video(
        fallback_provider="openai",
        fallback_model="gpt-4.1",
        prompt="show product",
        size="9:16",
        resolution="720p",
        duration_seconds=8,
        video_payload={"image_with_roles": [{"role": "first_frame", "image_url": "https://example.com/frame.png"}]},
        runtime_config={
            "video": {"provider_name": "apimart", "model_name": "doubao-seedance-2.0"},
            "trace_callback": lambda *args: events.append(args),
        },
    )

    assert result.task_id == "task-video-001"
    assert provider_name == "apimart"
    assert model_name == "doubao-seedance-2.0"
    event_type, _, payload = events[0]
    assert event_type == "provider_selection"
    assert payload["decision_type"] == "generation_provider_selection"
    assert payload["selected"] == "apimart/doubao-seedance-2.0"
    assert payload["options_considered"] == ["apimart/doubao-seedance-2.0", "openai/gpt-4.1"]
    assert payload["has_image_references"] is True


def test_human_integrity_instruction_only_applies_to_people_prompts():
    runtime = AgentsRuntime()

    assert runtime._human_integrity_instruction("Show a handbag on a marble table.") == ""
    assert "Human anatomy constraint" in runtime._human_integrity_instruction(
        "A real model wearing the dress walks slowly."
    )


def test_video_generation_prompt_includes_persona_contract():
    runtime = AgentsRuntime()
    runtime.providers = _FakeRegistry(_FakeVideoProvider())
    captured_prompts: list[str] = []

    def capture_chat(provider, model, prompt, runtime_config, **kwargs):
        captured_prompts.append(prompt)
        return '{"video_prompts":[{"variant_id":"V1","prompt":"Show the product in use."}]}', model, 0.0

    runtime._chat_complete = capture_chat
    runtime.run_video_generation(
        "persona-video-run",
        VideoScriptPack(
            scripts=[
                VideoScriptItem(
                    variant_id="V1",
                    hook="Hook",
                    script="Show the product.",
                )
            ],
            product_context={"product_name": "packing cube"},
        ),
        creative_specs={},
        provider="openai",
        model="gpt-4.1",
        runtime_config={
            "compiled_persona": {
                "lead_agent": {
                    "agent_name": "video_generation_agent",
                    "title": "Video Generation Agent",
                    "contract": {"mission": "Produce video assets from approved scripts."},
                },
                "collaborators": [],
            }
        },
    )

    assert "Persona Contract" in captured_prompts[0]
    assert "Video Generation Agent" in captured_prompts[0]


def test_video_scripting_uses_submitted_product_context_without_leash_defaults():
    runtime = AgentsRuntime()
    runtime._chat_complete = lambda *args, **kwargs: ("ok", "stub-model", 0.0)

    variant_set = VariantSet(
        variants=[
            VariantCandidate(
                variant_id="V1",
                angle="organized packing",
                hook="Pack faster without messy leaks",
                message="Keeps travel-size bottles upright and separated.",
            )
        ]
    )
    intake = ProductIntake(
        product_name="travel toiletry bag",
        business_context={},
        asset_media_summary="Compact zip organizer with clear compartments and upright bottle sleeves.",
    )

    output = runtime.run_video_scripting(
        run_id="runtime-script-generic-product",
        variant_set=variant_set,
        intake=intake,
        business_context={
            "target_audience": "frequent travelers",
            "key_value_props": ["keeps bottles upright", "clear compartments"],
            "primary_cta": "Shop Now",
        },
        provider="openai",
        model="gpt-4.1",
        creative_specs={"tiktok_video_style": "ugc_demo", "video_duration_seconds": 12},
        pipeline_mode="tiktok_shop_video",
    )

    first_script = output.payload["scripts"][0]
    script_text = " ".join(
        [
            first_script["hook"],
            first_script["script"],
            *first_script["shot_list"],
            *(first_script.get("tiktok", {}) or {}).get("on_screen_text", []),
        ]
    ).lower()
    assert "travel toiletry bag" in script_text
    assert "keeps bottles upright" in script_text
    for banned in ("leash", "collar", "harness", "dog walk", "sidewalk", "trail walkers"):
        assert banned not in script_text


def test_video_scripting_splits_long_duration_into_segments():
    runtime = AgentsRuntime()
    runtime._chat_complete = lambda *args, **kwargs: ("ok", "stub-model", 0.0)

    output = runtime.run_video_scripting(
        run_id="runtime-script-long-video",
        variant_set=VariantSet(
            variants=[
                VariantCandidate(
                    variant_id="V1",
                    angle="multi-scene styling",
                    hook="One dress, three moods",
                    message="Show the same dress across apartment, street, and evening scenes.",
                )
            ]
        ),
        intake=ProductIntake(
            product_name="olive satin dress",
            business_context={},
            asset_media_summary="Olive satin midi dress with twisted neckline and side ruching.",
        ),
        business_context={"target_audience": "fashion buyers", "primary_cta": "Shop the look"},
        provider="openai",
        model="gpt-4.1",
        creative_specs={"video_size": "9:16", "video_duration_seconds": 35},
        pipeline_mode="tiktok_shop_video",
    )

    segments = output.payload["scripts"][0]["segments"]
    assert [segment["duration_seconds"] for segment in segments] == [12.0, 12.0, 11.0]
    assert all(segment["duration_seconds"] <= 15 for segment in segments)
    assert [segment["shot_intent"] for segment in segments] == ["thumb_stop", "product_proof", "cta_packshot"]
    assert "one continuous ad" in segments[1]["motion_prompt"]
    assert "do not restart the hook" in segments[1]["motion_prompt"]
    assert "start_from_previous_tail_frame" in segments[1]["continuity_constraints"]
    assert "end_on_bridgeable_action_for_next_segment" in segments[0]["continuity_constraints"]
    assert segments[-1]["transition_to_next"] == "none"


def test_video_scripting_adds_human_motion_risk_constraint_for_model_segments():
    runtime = AgentsRuntime()
    runtime._chat_complete = lambda *args, **kwargs: ("ok", "stub-model", 0.0)

    output = runtime.run_video_scripting(
        run_id="runtime-script-human-motion-risk",
        variant_set=VariantSet(
            variants=[
                VariantCandidate(
                    variant_id="V1",
                    angle="model styling",
                    hook="A real model wears the dress",
                    message="Show the same model in a silver dress across scenes.",
                )
            ]
        ),
        intake=ProductIntake(
            product_name="silver dress",
            asset_media_summary="Reference image shows a real model wearing a silver dress.",
        ),
        business_context={"target_audience": "fashion buyers"},
        provider="openai",
        model="gpt-4.1",
        creative_specs={"video_duration_seconds": 32},
    )

    segments = output.payload["scripts"][0]["segments"]
    assert "avoid_high_risk_human_motion" in segments[1]["continuity_constraints"]


def test_planning_outputs_creative_director_and_production_plan():
    runtime = AgentsRuntime()
    runtime._chat_complete = lambda *args, **kwargs: ("planning summary", "stub-model", 0.0)
    intake = ProductIntake(
        product_name="Robe Dress",
        market="US",
        locale="en-US",
        business_context={
            "audience": "US women shopping for elegant comfortable robe dresses",
            "brief": "real model, bedroom morning, cafe, boutique mirror, evening lounge",
        },
        manual_research_brief="32-second segmented video with real human model and varied scenes.",
        asset_media_summary="Reference image shows the robe dress silhouette and fabric drape.",
        visual_identity={"must_preserve_details": ["robe dress silhouette", "fabric drape"]},
    )

    output = runtime.run_planning(
        run_id="planning-director",
        intake=intake,
        gm_lessons=[],
        creative_specs={"video_duration_seconds": 32, "max_video_segment_seconds": 15},
        enable_research=False,
        provider="openai",
        model="gpt-4.1",
    )

    plan = output.payload["creative_director_plan"]
    production = output.payload["production_plan"]
    assert plan["scene_arc"][0]["beat"] == "thumb_stop"
    assert "robe dress silhouette" in plan["must_preserve_visuals"]
    assert any("bedroom morning" in scene for scene in plan["scene_hints"])
    assert production["segment_strategy"]["estimated_segment_count"] == 3
    assert output.payload["quality_gates"][0]["gate"] == "product_truth_lock"


def test_video_scripting_carries_planning_director_plan_into_fallback():
    runtime = AgentsRuntime()
    runtime._chat_complete = lambda *args, **kwargs: ("ok", "stub-model", 0.0)
    planning = PlanningBrief(
        strategic_angles=["travel order"],
        creative_director_plan={
            "emotional_beats": ["relief", "confidence"],
            "must_preserve_visuals": ["clear compartments", "upright bottle sleeves"],
            "scene_arc": [
                {"beat": "thumb_stop", "scene_direction": "messy hotel counter transforms into organized kit"},
                {"beat": "proof", "scene_direction": "close-up bottles stay upright inside clear sleeves"},
            ],
        },
        production_plan={"segment_strategy": {"estimated_segment_count": 1}},
        quality_gates=[{"gate": "product_truth_lock"}],
    )

    output = runtime.run_video_scripting(
        run_id="runtime-script-director-plan",
        variant_set=VariantSet(
            variants=[
                VariantCandidate(
                    variant_id="V1",
                    angle="travel order",
                    hook="Pack without leaks",
                    message="Keep bottles upright in transit.",
                )
            ]
        ),
        intake=ProductIntake(
            product_name="travel toiletry bag",
            asset_media_summary="Compact organizer with clear compartments.",
        ),
        business_context={"target_audience": "frequent travelers", "primary_cta": "Shop Now"},
        provider="openai",
        model="gpt-4.1",
        creative_specs={"video_duration_seconds": 12},
        planning=planning,
    )

    first_script = output.payload["scripts"][0]
    assert output.payload["director_strategy"]["creative_director_plan"]["emotional_beats"] == ["relief", "confidence"]
    assert "messy hotel counter" in first_script["shot_list"][0]
    assert "clear compartments" in first_script["shot_list"][0]
    assert "Cold open" in first_script["script"]
    assert "overlay:" in first_script["shot_list"][0]
    assert first_script["shot_plan"][0]["first_frame"]["description"] == first_script["shot_list"][0]


def test_video_generation_stitches_completed_segments(monkeypatch):
    runtime = AgentsRuntime()
    provider = _FakeCompletedVideoProvider()
    runtime.providers = _FakeRegistry(provider)
    runtime._chat_complete = lambda *args, **kwargs: ("ok", "stub-model", 0.0)

    def fake_extract_last_frame(*, video_path, output_path):
        output_path.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"))
        return str(output_path)

    def fake_stitch(*, video_paths, output_path):
        output_path.write_bytes(b"stitched-video" * 256)
        return str(output_path)

    monkeypatch.setattr("app.agents.runtime.extract_last_video_frame", fake_extract_last_frame)
    monkeypatch.setattr("app.agents.runtime.stitch_video_files", fake_stitch)

    script_pack = VideoScriptPack(
        scripts=[
            VideoScriptItem(
                variant_id="V1",
                hook="One dress, three moods",
                script="A segmented long-form short ad.",
                segments=[
                    {
                        "segment_id": "V1_S1",
                        "variant_id": "V1",
                        "duration_seconds": 12,
                        "first_frame_prompt": "apartment reveal",
                        "last_frame_prompt": "walking out",
                        "motion_prompt": "model smiles in apartment",
                    },
                    {
                        "segment_id": "V1_S2",
                        "variant_id": "V1",
                        "duration_seconds": 12,
                        "first_frame_prompt": "street",
                        "last_frame_prompt": "cafe",
                        "motion_prompt": "model crosses street",
                    },
                    {
                        "segment_id": "V1_S3",
                        "variant_id": "V1",
                        "duration_seconds": 11,
                        "first_frame_prompt": "evening",
                        "last_frame_prompt": "cta",
                        "motion_prompt": "model enters evening scene",
                    },
                ],
            )
        ],
        product_context={"product_name": "olive satin dress"},
        generation_spec={"size": "9:16", "resolution": "720p", "duration": 35},
    )

    output = runtime.run_video_generation(
        run_id="runtime-video-segments",
        script_pack=script_pack,
        creative_specs={"video_size": "9:16", "video_duration_seconds": 35},
        provider="openai",
        model="gpt-4.1",
        runtime_config={"video": {"provider_name": "fake", "model_name": "fake-video"}, "force_regenerate": True},
    )

    video = output.payload["videos"][0]
    assert [request.duration_seconds for request in provider.requests] == [12, 12, 11]
    assert all(request.return_last_frame is True for request in provider.requests)
    assert provider.requests[1].image_with_roles == [{"url": "https://example.com/last-1.png", "role": "first_frame"}]
    assert provider.requests[2].image_with_roles == [{"url": "https://example.com/last-2.png", "role": "first_frame"}]
    assert video["segments"][1]["reference_mode"] == "first_frame"
    assert video["segments"][1]["reference_image_count"] == 1
    assert "only opening hook" in provider.requests[0].prompt
    assert "Continue the exact action from the supplied first_frame reference" in provider.requests[1].prompt
    assert "do not restart with a new intro" in provider.requests[2].prompt
    assert video["source"] == "stitched_segments"
    assert video["duration_seconds"] == 35.0
    assert len(video["segments"]) == 3
    assert video["video_uri"].endswith("V1_stitched.mp4")


def test_segmented_video_generation_uses_local_tail_frame_with_identity_anchors(monkeypatch):
    runtime = AgentsRuntime()
    provider = _FakeCompletedVideoProviderWithoutLastFrameUrl()
    runtime.providers = _FakeRegistry(provider)
    runtime._chat_complete = lambda *args, **kwargs: ("ok", "stub-model", 0.0)

    def fake_extract_last_frame(*, video_path, output_path):
        output_path.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"))
        return str(output_path)

    def fake_stitch(*, video_paths, output_path):
        output_path.write_bytes(b"stitched-video" * 256)
        return str(output_path)

    monkeypatch.setattr("app.agents.runtime.extract_last_video_frame", fake_extract_last_frame)
    monkeypatch.setattr("app.agents.runtime.stitch_video_files", fake_stitch)

    script_pack = VideoScriptPack(
        scripts=[
            VideoScriptItem(
                variant_id="V1",
                hook="One dress, two moods",
                script="A continuous segmented ad.",
                segments=[
                    {
                        "segment_id": "V1_S1",
                        "variant_id": "V1",
                        "duration_seconds": 12,
                        "first_frame_prompt": "apartment reveal",
                        "last_frame_prompt": "walking out",
                        "motion_prompt": "model smiles in apartment",
                    },
                    {
                        "segment_id": "V1_S2",
                        "variant_id": "V1",
                        "duration_seconds": 12,
                        "first_frame_prompt": "street continuation",
                        "last_frame_prompt": "cta",
                        "motion_prompt": "same model crosses street",
                    },
                ],
            )
        ],
        product_context={"product_name": "silver dress"},
        generation_spec={"size": "9:16", "resolution": "720p", "duration": 24},
    )

    output = runtime.run_video_generation(
        run_id="runtime-video-local-tail",
        script_pack=script_pack,
        storyboard_frames=[{"raw_response": {"image_url": "https://example.com/storyboard-anchor.png"}}],
        creative_specs={"video_size": "9:16", "video_duration_seconds": 24},
        provider="openai",
        model="gpt-4.1",
        runtime_config={"video": {"provider_name": "fake", "model_name": "fake-video"}, "force_regenerate": True},
    )

    assert output.payload["videos"][0]["source"] == "stitched_segments"
    assert provider.requests[0].image_urls == ["https://example.com/storyboard-anchor.png"]
    assert provider.requests[1].image_with_roles == []
    assert provider.requests[1].image_urls[0].startswith("data:image/png;base64,")
    assert provider.requests[1].image_urls[1] == "https://example.com/storyboard-anchor.png"
    assert "image 1 is the previous segment tail frame" in provider.requests[1].prompt


def test_apimart_segmented_video_skips_unhosted_local_tail_frame(monkeypatch):
    runtime = AgentsRuntime()
    provider = _FakeCompletedVideoProviderWithoutLastFrameUrl()
    runtime.providers = _FakeRegistry(provider)
    runtime._chat_complete = lambda *args, **kwargs: ("ok", "stub-model", 0.0)

    def fake_extract_last_frame(*, video_path, output_path):
        output_path.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"))
        return str(output_path)

    def fake_stitch(*, video_paths, output_path):
        output_path.write_bytes(b"stitched-video" * 256)
        return str(output_path)

    monkeypatch.setattr("app.agents.runtime.extract_last_video_frame", fake_extract_last_frame)
    monkeypatch.setattr("app.agents.runtime.stitch_video_files", fake_stitch)

    script_pack = VideoScriptPack(
        scripts=[
            VideoScriptItem(
                variant_id="V1",
                hook="One dress, two moods",
                script="A continuous segmented ad.",
                segments=[
                    {"segment_id": "V1_S1", "variant_id": "V1", "duration_seconds": 12, "motion_prompt": "model in apartment"},
                    {"segment_id": "V1_S2", "variant_id": "V1", "duration_seconds": 12, "motion_prompt": "same model in street"},
                ],
            )
        ],
        product_context={"product_name": "silver dress"},
        generation_spec={"size": "9:16", "resolution": "720p", "duration": 24},
    )

    output = runtime.run_video_generation(
        run_id="runtime-video-apimart-no-data-tail",
        script_pack=script_pack,
        storyboard_frames=[{"raw_response": {"image_url": "https://example.com/storyboard-anchor.png"}}],
        creative_specs={"video_size": "9:16", "video_duration_seconds": 24},
        provider="openai",
        model="gpt-4.1",
        runtime_config={
            "video": {"provider_name": "apimart", "model_name": "doubao-seedance-2.0"},
            "force_regenerate": True,
        },
    )

    assert output.payload["videos"][0]["source"] == "stitched_segments"
    assert provider.requests[1].image_urls == ["https://example.com/storyboard-anchor.png"]
    assert provider.requests[1].image_with_roles == []
    assert output.payload["videos"][0]["segments"][1]["reference_mode"] == "anchors"


def test_segmented_video_generation_truncates_refs_when_provider_accepts_one_image(monkeypatch, tmp_path):
    runtime = AgentsRuntime()
    provider = _FakeCompletedVideoProviderWithoutLastFrameUrl()
    runtime.providers = _FakeRegistry(provider)
    runtime._chat_complete = lambda *args, **kwargs: ("ok", "stub-model", 0.0)
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC")
    anchor = tmp_path / "storyboard_anchor.png"
    anchor.write_bytes(png)

    def fake_extract_last_frame(*, video_path, output_path):
        output_path.write_bytes(png)
        return str(output_path)

    def fake_stitch(*, video_paths, output_path):
        output_path.write_bytes(b"stitched-video" * 256)
        return str(output_path)

    monkeypatch.setattr("app.agents.runtime.extract_last_video_frame", fake_extract_last_frame)
    monkeypatch.setattr("app.agents.runtime.stitch_video_files", fake_stitch)

    script_pack = VideoScriptPack(
        scripts=[
            VideoScriptItem(
                variant_id="V1",
                hook="One dress, two moods",
                script="A continuous segmented ad.",
                segments=[
                    {"segment_id": "V1_S1", "variant_id": "V1", "duration_seconds": 12, "motion_prompt": "apartment"},
                    {"segment_id": "V1_S2", "variant_id": "V1", "duration_seconds": 12, "motion_prompt": "street"},
                ],
            )
        ],
        product_context={"product_name": "silver dress"},
        generation_spec={"size": "9:16", "resolution": "720p", "duration": 24},
    )

    runtime.run_video_generation(
        run_id="runtime-video-reference-board",
        script_pack=script_pack,
        storyboard_frames=[{"image_uri": str(anchor)}],
        creative_specs={"video_size": "9:16", "video_duration_seconds": 24, "max_reference_images": 1},
        provider="openai",
        model="gpt-4.1",
        runtime_config={"video": {"provider_name": "fake", "model_name": "fake-video"}, "force_regenerate": True},
    )

    assert len(provider.requests[1].image_urls) == 1
    assert provider.requests[1].image_urls[0].startswith("data:image/png;base64,")
    assert provider.requests[1].image_with_roles == []
    assert "previous segment tail frame" in provider.requests[1].prompt


def test_segmented_video_generation_preserves_initial_role_references(monkeypatch):
    runtime = AgentsRuntime()
    provider = _FakeCompletedVideoProvider()
    runtime.providers = _FakeRegistry(provider)
    runtime._chat_complete = lambda *args, **kwargs: ("ok", "stub-model", 0.0)

    def fake_extract_last_frame(*, video_path, output_path):
        output_path.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"))
        return str(output_path)

    def fake_stitch(*, video_paths, output_path):
        output_path.write_bytes(b"stitched-video" * 256)
        return str(output_path)

    monkeypatch.setattr("app.agents.runtime.extract_last_video_frame", fake_extract_last_frame)
    monkeypatch.setattr("app.agents.runtime.stitch_video_files", fake_stitch)

    runtime.run_video_generation(
        run_id="runtime-video-role-refs",
        script_pack=VideoScriptPack(
            scripts=[
                VideoScriptItem(
                    variant_id="V1",
                    hook="One dress",
                    script="A continuous segmented ad.",
                    segments=[
                        {"segment_id": "V1_S1", "variant_id": "V1", "duration_seconds": 8, "motion_prompt": "start"},
                        {"segment_id": "V1_S2", "variant_id": "V1", "duration_seconds": 8, "motion_prompt": "continue"},
                    ],
                )
            ],
            product_context={"product_name": "silver dress"},
            generation_spec={"size": "9:16", "resolution": "720p", "duration": 16},
        ),
        creative_specs={
            "video_size": "9:16",
            "video_duration_seconds": 16,
            "image_with_roles": [{"url": "https://example.com/start.png", "role": "first_frame"}],
        },
        provider="openai",
        model="gpt-4.1",
        runtime_config={"video": {"provider_name": "fake", "model_name": "fake-video"}, "force_regenerate": True},
    )

    assert provider.requests[0].image_with_roles == [{"url": "https://example.com/start.png", "role": "first_frame"}]
    assert provider.requests[0].image_urls == []
    assert "role references exactly as temporal anchors" in provider.requests[0].prompt
    assert provider.requests[1].image_with_roles == [{"url": "https://example.com/last-1.png", "role": "first_frame"}]


def test_single_video_generation_truncates_refs_when_provider_accepts_one_image():
    runtime = AgentsRuntime()
    provider = _FakeVideoProvider()
    runtime.providers = _FakeRegistry(provider)
    runtime._chat_complete = lambda *args, **kwargs: ("ok", "stub-model", 0.0)
    png_data_url = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"

    runtime.run_video_generation(
        run_id="runtime-video-single-reference-board",
        script_pack=VideoScriptPack(
            scripts=[
                VideoScriptItem(
                    variant_id="V1",
                    hook="One dress",
                    script="Show one continuous social ad.",
                    shot_list=["show model wearing the dress"],
                )
            ],
            product_context={"product_name": "silver dress"},
            generation_spec={"size": "9:16", "resolution": "720p", "duration": 12},
        ),
        creative_specs={
            "video_size": "9:16",
            "video_duration_seconds": 12,
            "image_urls": [png_data_url, png_data_url],
            "max_reference_images": 1,
        },
        provider="openai",
        model="gpt-4.1",
        runtime_config={"video": {"provider_name": "fake", "model_name": "fake-video"}},
    )

    assert provider.last_request is not None
    assert len(provider.last_request.image_urls) == 1
    assert provider.last_request.image_urls[0].startswith("data:image/png;base64,")


def test_segmented_video_generation_marks_first_segment_submit_failure(monkeypatch):
    runtime = AgentsRuntime()
    runtime._chat_complete = lambda *args, **kwargs: ("ok", "stub-model", 0.0)
    monkeypatch.setattr(
        runtime,
        "_generate_video_clip_payload",
        lambda **kwargs: (
            {
                "variant_id": kwargs["variant_id"],
                "video_uri": "assets/run/V1_generation_error.txt",
                "source": "placeholder",
                "generation_status": None,
                "error": "payment_required",
            },
            0.0,
            "",
        ),
    )

    output = runtime.run_video_generation(
        run_id="runtime-video-first-segment-failure",
        script_pack=VideoScriptPack(
            scripts=[
                VideoScriptItem(
                    variant_id="V1",
                    hook="Hook",
                    script="Script",
                    segments=[
                        {
                            "segment_id": "V1_S1",
                            "variant_id": "V1",
                            "duration_seconds": 12,
                            "motion_prompt": "first segment",
                        }
                    ],
                )
            ],
            product_context={"product_name": "robe dress"},
            generation_spec={"size": "9:16", "resolution": "720p", "duration": 12},
        ),
        creative_specs={"video_size": "9:16", "video_duration_seconds": 12},
        provider="apimart",
        model="doubao-seedance-2.0",
    )

    video = output.payload["videos"][0]
    assert video["generation_status"] == "failed"
    assert video["source"] == "placeholder"
    assert video["error"] == "payment_required"


def test_storyboard_and_video_generation_do_not_inject_leash_defaults_and_use_structured_specs():
    runtime = AgentsRuntime()
    runtime._chat_complete = lambda *args, **kwargs: ("ok", "stub-model", 0.0)

    def fake_generate_image(*, prompt, **kwargs):
        assert "dog leash" not in prompt.lower()
        assert "leash" not in prompt.lower()
        return (
            type(
                "ImageResult",
                (),
                {
                    "estimated_cost": 0.0,
                    "images": [],
                },
            )(),
            "stub-image-provider",
            "stub-image-model",
        )

    fake_provider = _FakeVideoProvider()
    runtime._generate_image = fake_generate_image
    runtime.providers = _FakeRegistry(fake_provider)

    script_pack = VideoScriptPack(
        scripts=[
            VideoScriptItem(
                variant_id="V1",
                hook="Pack faster without messy leaks",
                script="Show the travel toiletry bag holding upright bottles in clear compartments.",
                shot_list=[
                    "Open the bag on a hotel bathroom counter.",
                    "Close-up of upright bottle sleeves and clear compartments.",
                    "Packed bag slides neatly into a carry-on.",
                ],
            )
        ],
        product_context={"product_name": "travel toiletry bag", "audience": "frequent travelers"},
        generation_spec={"size": "16:9", "resolution": "720p", "duration": 5},
    )

    storyboard_output = runtime.run_storyboard_image_generation(
        run_id="runtime-storyboard-generic-product",
        script_pack=script_pack,
        provider="openai",
        model="gpt-4.1",
        creative_specs={"video_size": "9:16"},
    )
    storyboard_prompt = storyboard_output.payload["frames"][0]["prompt"].lower()
    assert "dog leash" not in storyboard_prompt
    assert "travel toiletry bag" in storyboard_prompt

    video_output = runtime.run_video_generation(
        run_id="runtime-video-generic-product",
        script_pack=script_pack,
        creative_specs={
            "video_size": "16:9",
            "resolution": "720p",
            "video_duration_seconds": 5,
            "generate_audio": True,
            "return_last_frame": True,
            "seed": 42,
            "tools": [{"type": "web_search"}],
            "image_urls": ["https://example.com/reference-image.png"],
            "audio_urls": ["https://example.com/reference-audio.wav"],
        },
        provider="apimart",
        model="doubao-seedance-2.0",
        runtime_config={
            "api_base_url": "https://api.apimart.ai/v1/videos/generations",
            "api_key": "dummy",
        },
    )

    video_payload = video_output.payload["videos"][0]
    assert "leash" not in video_payload["prompt"].lower()
    assert "leash_connection_required" not in video_payload.get("quality_constraints", {})
    assert fake_provider.last_request is not None
    assert fake_provider.last_request.generate_audio is True
    assert fake_provider.last_request.return_last_frame is True
    assert fake_provider.last_request.seed == 42
    assert fake_provider.last_request.tools == [{"type": "web_search"}]
    assert fake_provider.last_request.image_urls == ["https://example.com/reference-image.png"]
    assert fake_provider.last_request.audio_urls == ["https://example.com/reference-audio.wav"]


def test_storyboard_prompt_uses_director_plan_without_category_lock():
    runtime = AgentsRuntime()
    runtime._chat_complete = lambda *args, **kwargs: ("ok", "stub-model", 0.0)
    planning = PlanningBrief(
        creative_director_plan={
            "emotional_beats": ["relief"],
            "must_preserve_visuals": ["clear compartments", "upright bottle sleeves"],
            "scene_arc": [
                {"beat": "proof", "scene_direction": "hotel bathroom counter with bottles standing upright"},
            ],
        },
        quality_gates=[{"gate": "category_fit_storyboard"}],
    )
    script_pack = VideoScriptPack(
        scripts=[
            VideoScriptItem(
                variant_id="V1",
                hook="No more suitcase leaks",
                script="Show a compact organizer solving messy travel packing.",
                shot_list=["Open the organizer on a hotel counter"],
            )
        ],
        product_context={"product_name": "travel toiletry bag", "audience": "frequent travelers"},
        generation_spec={"size": "9:16", "resolution": "720p", "duration": 5},
    )

    output = runtime.run_storyboard_image_generation(
        run_id="storyboard-director-generic-product",
        script_pack=script_pack,
        provider="openai",
        model="gpt-4.1",
        creative_specs={"video_size": "9:16"},
        planning=planning,
    )

    prompt = output.payload["frames"][0]["prompt"].lower()
    assert "hotel bathroom counter" in prompt
    assert "emotional target: relief" in prompt
    assert "clear compartments" in prompt
    assert "do not force fashion/model framing" in prompt


def test_storyboard_frame_exposes_pending_candidate_task(monkeypatch):
    runtime = AgentsRuntime()
    runtime._chat_complete = lambda *args, **kwargs: ("ok", "stub-model", 0.0)

    def fake_generate_image(*, prompt, **kwargs):
        return (
            type(
                "ImageResult",
                (),
                {
                    "estimated_cost": 0.0,
                    "images": [],
                    "task_id": "image-task-1",
                    "status": "submitted",
                    "raw_response": {"id": "image-task-1"},
                },
            )(),
            "stub-image-provider",
            "stub-image-model",
        )

    monkeypatch.setattr(runtime, "_generate_image", fake_generate_image)

    output = runtime.run_storyboard_image_generation(
        run_id="storyboard-pending-candidate",
        script_pack=VideoScriptPack(
            scripts=[
                VideoScriptItem(
                    variant_id="V1",
                    hook="Hook",
                    script="Script",
                    shot_list=["Shot 1"],
                )
            ],
            product_context={"product_name": "travel organizer"},
            generation_spec={"size": "9:16", "duration": 5},
        ),
        provider="openai",
        model="gpt-4.1",
        creative_specs={"video_size": "9:16"},
    )

    frame = output.payload["frames"][0]
    assert frame["external_task_id"] == "image-task-1"
    assert frame["generation_status"] == "submitted"
    assert frame["candidate_frames"][0]["external_task_id"] == "image-task-1"


def test_storyboard_generation_can_store_multiple_candidates_and_pick_one(monkeypatch):
    runtime = AgentsRuntime()
    runtime._chat_complete = lambda *args, **kwargs: ("ok", "stub-model", 0.0)

    candidate_scores = {
        "_cand_1": 61.0,
        "_cand_2": 93.0,
        "_cand_3": 77.0,
    }

    def fake_generate_image(*, prompt, **kwargs):
        image_result = type(
            "ImageResult",
            (),
            {
                "estimated_cost": 0.0,
                "images": [
                    type(
                        "GeneratedImage",
                        (),
                        {
                            "b64_json": base64.b64encode(b"candidate-image-bytes").decode("ascii"),
                            "url": None,
                        },
                    )()
                ],
            },
        )()
        return image_result, "stub-image-provider", "stub-image-model"

    def fake_local_media_qa(*, uri, **kwargs):
        score = next((value for marker, value in candidate_scores.items() if marker in str(uri)), 0.0)
        return {"status": "pass", "score": score, "flags": []}

    monkeypatch.setattr(runtime, "_generate_image", fake_generate_image)
    monkeypatch.setattr(runtime, "_local_media_qa", fake_local_media_qa)

    script_pack = VideoScriptPack(
        scripts=[
            VideoScriptItem(
                variant_id="V1",
                hook="Pack faster without messy leaks",
                script="Show the travel toiletry bag holding upright bottles in clear compartments.",
                shot_list=["Open the bag", "Show bottles upright", "Packshot CTA"],
            )
        ],
        product_context={"product_name": "travel toiletry bag", "audience": "frequent travelers"},
        generation_spec={"size": "9:16", "resolution": "720p", "duration": 5},
    )

    output = runtime.run_storyboard_image_generation(
        run_id="storyboard-candidates",
        script_pack=script_pack,
        provider="openai",
        model="gpt-4.1",
        creative_specs={"video_size": "9:16", "storyboard_candidate_count": 3},
    )

    frame = output.payload["frames"][0]
    assert frame["selected_candidate_index"] == 1
    assert len(frame["candidate_frames"]) == 3
    assert [candidate["candidate_index"] for candidate in frame["candidate_frames"]] == [0, 1, 2]
    assert frame["candidate_frames"][1]["image_uri"] == frame["image_uri"]
    assert frame["candidate_frames"][1]["visual_qa"]["score"] == frame["visual_qa"]["score"] == 93.0
    assert frame["candidate_frames"][1]["source"] == "b64_json"


def test_video_generation_samples_frames_for_completed_local_videos(tmp_path, monkeypatch):
    runtime = AgentsRuntime()
    runtime._chat_complete = lambda *args, **kwargs: ('{"video_prompts":[{"variant_id":"V1","prompt":"demo prompt"}]}', "stub-model", 0.0)

    script_pack = VideoScriptPack(
        scripts=[
            VideoScriptItem(
                variant_id="V1",
                hook="Show the result immediately",
                script="Open with the product in use and end on a clean CTA.",
                shot_list=["Open on product close-up", "Demonstrate use", "Finish with CTA"],
            )
        ],
        product_context={"product_name": "travel toiletry bag"},
        generation_spec={"size": "9:16", "resolution": "720p", "duration": 5},
    )

    fake_video_bytes = b"\x00\x00\x00\x20ftypisom" + (b"0" * 2048)

    monkeypatch.setattr(
        runtime,
        "_generate_video_submit_only",
        lambda **kwargs: (
            VideoGenResult(
                model_used="stub-video-model",
                status="completed",
                videos=[
                    GeneratedVideo(
                        b64_data=base64.b64encode(fake_video_bytes).decode("ascii"),
                        task_id="video-task-1",
                        status="completed",
                    )
                ],
            ),
            "stub-video-provider",
            "stub-video-model",
        ),
    )

    def fake_sample_video_frames(*, video_path, output_dir, prefix, count=3):
        output_dir.mkdir(parents=True, exist_ok=True)
        frames = []
        for idx in range(count):
            frame = output_dir / f"{prefix}_frame_{idx + 1}.png"
            frame.write_bytes(f"frame-{idx + 1}".encode("ascii"))
            frames.append(str(frame))
        return frames

    monkeypatch.setattr("app.agents.runtime.sample_video_frames", fake_sample_video_frames)

    output = runtime.run_video_generation(
        run_id="runtime-video-frame-sampling",
        script_pack=script_pack,
        creative_specs={"video_size": "9:16", "resolution": "720p", "video_duration_seconds": 5},
        provider="openai",
        model="gpt-4.1",
    )

    video_payload = output.payload["videos"][0]
    assert video_payload["generation_status"] == "completed"
    assert len(video_payload["frame_uris"]) == 3
    assert len(video_payload["generated_video_frames"]) == 3
    assert all(Path(frame["uri"]).exists() for frame in video_payload["generated_video_frames"])
    assert video_payload["frame_uris"] == [frame["uri"] for frame in video_payload["generated_video_frames"]]


def test_attach_generated_video_frames_clears_stale_frame_metadata_when_resampling_returns_none(monkeypatch):
    runtime = AgentsRuntime()
    monkeypatch.setattr(runtime, "_sample_generated_video_frames", lambda **kwargs: ([], []))

    enriched = runtime._attach_generated_video_frames(
        run_id="runtime-video-clear-stale-frames",
        video_payload={
            "variant_id": "V1",
            "video_uri": "assets/runtime-video-clear-stale-frames/V1.mp4",
            "generation_status": "completed",
            "frame_uris": ["assets/old_frame_1.png"],
            "generated_video_frames": [{"uri": "assets/old_frame_1.png"}],
        },
    )

    assert enriched["frame_uris"] == []
    assert enriched["generated_video_frames"] == []


def test_visual_quality_assessment_uses_frame_review_for_completed_videos(tmp_path):
    runtime = AgentsRuntime()
    runtime._chat_complete = lambda *args, **kwargs: ("frame review notes", "stub-model", 0.0)

    video_path = tmp_path / "completed.mp4"
    video_path.write_bytes(b"\x00\x00\x00\x20ftypisom" + (b"1" * 2048))

    variant_set = VariantSet(
        variants=[
            VariantCandidate(
                variant_id="V1",
                angle="show the product immediately",
                hook="The first second should explain the product",
                message="Lead with the product and keep continuity clean.",
            )
        ]
    )

    output = runtime.run_visual_quality_assessment(
        run_id="runtime-video-frame-review",
        variant_set=variant_set,
        videos={
            "videos": [
                {
                    "variant_id": "V1",
                    "video_uri": str(video_path),
                    "uri": str(video_path),
                    "generation_status": "completed",
                    "source": "local_file",
                }
            ]
        },
        video_scripts={
            "scripts": [
                {
                    "variant_id": "V1",
                    "hook": "The first second should explain the product",
                    "shot_plan": [
                        {
                            "shot_id": "shot-1",
                            "intent": "thumb_stop",
                            "duration_seconds": 1.5,
                            "product_continuity_constraints": ["same blue bottle", "same cap shape"],
                        }
                    ],
                }
            ]
        },
        social_review_contract={
            "review_profile": "social_video",
            "required_checks": ["first_frame_clarity", "continuity"],
        },
        provider="openai",
        model="gpt-4.1",
    )

    summary = output.payload["variant_summaries"][0]
    report = output.payload["reports"][0]
    asset_report = report["asset_reports"][0]

    assert summary["recommended_action"] == "manual_review"
    assert summary["qa_status"] == "warn"
    assert "visual_qa_needs_frame_review" in asset_report["flags"]
    assert any(check["status"] == "manual_review" for check in asset_report["checks"])


def test_visual_quality_assessment_flags_human_anatomy_review_for_model_videos(tmp_path):
    runtime = AgentsRuntime()
    runtime._chat_complete = lambda *args, **kwargs: ("human review notes", "stub-model", 0.0)

    video_path = tmp_path / "model.mp4"
    video_path.write_bytes(b"\x00\x00\x00\x20ftypisom" + (b"1" * 2048))

    output = runtime.run_visual_quality_assessment(
        run_id="runtime-video-human-review",
        variant_set=VariantSet(
            variants=[
                VariantCandidate(
                    variant_id="V1",
                    angle="model styling",
                    hook="A model wearing the dress walks slowly",
                    message="Keep the same model and dress visible.",
                )
            ]
        ),
        videos={
            "videos": [
                {
                    "variant_id": "V1",
                    "video_uri": str(video_path),
                    "uri": str(video_path),
                    "generation_status": "completed",
                    "source": "local_file",
                    "prompt": "A real model wearing the silver dress.",
                }
            ]
        },
        provider="openai",
        model="gpt-4.1",
    )

    summary = output.payload["variant_summaries"][0]
    asset_report = output.payload["reports"][0]["asset_reports"][0]
    assert summary["qa_status"] == "warn"
    assert summary["recommended_action"] == "manual_review"
    assert "visual_qa_human_anatomy_review" in asset_report["flags"]


def test_visual_quality_assessment_treats_unusable_extracted_frames_as_manual_review(tmp_path):
    runtime = AgentsRuntime()
    runtime._chat_complete = lambda *args, **kwargs: ("frame review notes", "stub-model", 0.0)

    video_path = tmp_path / "completed.mp4"
    video_path.write_bytes(b"\x00\x00\x00\x20ftypisom" + (b"1" * 2048))

    frame_paths = []
    for idx in range(3):
        frame_path = tmp_path / f"placeholder_{idx + 1}.png"
        frame_path.write_bytes(b"")
        frame_paths.append(str(frame_path))

    variant_set = VariantSet(
        variants=[
            VariantCandidate(
                variant_id="V1",
                angle="clear product intro",
                hook="Lead with the product immediately",
                message="Open strong and keep the edit truthful.",
            )
        ]
    )

    output = runtime.run_visual_quality_assessment(
        run_id="runtime-video-unusable-frames",
        variant_set=variant_set,
        videos={
            "videos": [
                {
                    "variant_id": "V1",
                    "video_uri": str(video_path),
                    "uri": str(video_path),
                    "generation_status": "completed",
                    "source": "local_file",
                    "frame_uris": frame_paths,
                }
            ]
        },
        social_review_contract={"review_profile": "social_video", "required_checks": []},
        provider="openai",
        model="gpt-4.1",
    )

    summary = output.payload["variant_summaries"][0]
    asset_report = output.payload["reports"][0]["asset_reports"][0]

    assert summary["recommended_action"] == "manual_review"
    assert summary["qa_status"] == "warn"
    assert "visual_qa_unusable_frame_sequence" in asset_report["flags"]
    assert any(check["key"] == "frame_sequence_quality" and check["status"] == "manual_review" for check in asset_report["checks"])


def test_visual_quality_assessment_surfaces_required_frame_checks_without_shot_plan(tmp_path):
    runtime = AgentsRuntime()
    runtime._chat_complete = lambda *args, **kwargs: ("frame review notes", "stub-model", 0.0)

    video_path = tmp_path / "completed.mp4"
    video_path.write_bytes(b"\x00\x00\x00\x20ftypisom" + (b"1" * 2048))

    frame_paths = []
    for idx in range(3):
        frame_path = tmp_path / f"usable_{idx + 1}.png"
        frame_path.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFElEQVR42mP8z/CfAQgwgImBASwAAB0JAgm1nxsAAAAASUVORK5CYII="))
        frame_paths.append(str(frame_path))

    variant_set = VariantSet(
        variants=[
            VariantCandidate(
                variant_id="V1",
                angle="truthful demo",
                hook="Show what the buyer gets",
                message="Keep continuity and CTA readable.",
            )
        ]
    )

    output = runtime.run_visual_quality_assessment(
        run_id="runtime-video-required-checks",
        variant_set=variant_set,
        videos={
            "videos": [
                {
                    "variant_id": "V1",
                    "video_uri": str(video_path),
                    "uri": str(video_path),
                    "generation_status": "completed",
                    "source": "local_file",
                    "frame_uris": frame_paths,
                }
            ]
        },
        social_review_contract={
            "review_profile": "social_video",
            "required_checks": ["continuity", "product_truth", "cta_clarity"],
        },
        provider="openai",
        model="gpt-4.1",
    )

    summary = output.payload["variant_summaries"][0]
    asset_report = output.payload["reports"][0]["asset_reports"][0]

    assert summary["recommended_action"] == "manual_review"
    assert summary["qa_status"] == "warn"
    assert "visual_qa_continuity_frame_check" in asset_report["flags"]
    assert "visual_qa_product_truth_frame_check" in asset_report["flags"]
    assert "visual_qa_cta_clarity_frame_check" in asset_report["flags"]
    assert any(check["key"] == "continuity" and check["status"] == "manual_review" for check in asset_report["checks"])
    assert any(check["key"] == "product_truth" and check["status"] == "manual_review" for check in asset_report["checks"])
    assert any(check["key"] == "cta_clarity" and check["status"] == "manual_review" for check in asset_report["checks"])


# ---------------------------------------------------------------------------
# _parse_llm_json tests
# ---------------------------------------------------------------------------

def test_parse_llm_json_valid_raw():
    runtime = AgentsRuntime()
    result = runtime._parse_llm_json('{"scripts": [1, 2, 3]}', "scripts")
    assert result == {"scripts": [1, 2, 3]}


def test_parse_llm_json_valid_with_fence():
    runtime = AgentsRuntime()
    result = runtime._parse_llm_json(
        '```json\n{"frames": [{"id": 1}]}\n```',
        "frames",
    )
    assert result == {"frames": [{"id": 1}]}


def test_parse_llm_json_valid_with_plain_fence():
    runtime = AgentsRuntime()
    result = runtime._parse_llm_json(
        '```\n{"video_prompts": ["prompt1"]}\n```',
        "video_prompts",
    )
    assert result == {"video_prompts": ["prompt1"]}


def test_parse_llm_json_strips_surrounding_whitespace():
    runtime = AgentsRuntime()
    result = runtime._parse_llm_json(
        '  \n{"key": "value"}\n  ',
        "key",
    )
    assert result == {"key": "value"}


def test_parse_llm_json_returns_full_dict_not_just_value():
    runtime = AgentsRuntime()
    result = runtime._parse_llm_json(
        '{"scripts": [1, 2], "meta": {"model": "gpt-4"}}',
        "scripts",
    )
    assert result == {"scripts": [1, 2], "meta": {"model": "gpt-4"}}


def test_parse_llm_json_empty_string_raises():
    runtime = AgentsRuntime()
    with pytest.raises(ValueError, match="empty"):
        runtime._parse_llm_json("", "scripts")


def test_parse_llm_json_whitespace_only_raises():
    runtime = AgentsRuntime()
    with pytest.raises(ValueError, match="empty"):
        runtime._parse_llm_json("   \n  \t  ", "scripts")


def test_parse_llm_json_invalid_json_raises():
    runtime = AgentsRuntime()
    with pytest.raises(ValueError, match="Failed to parse"):
        runtime._parse_llm_json("not valid json", "scripts")


def test_parse_llm_json_missing_schema_key_raises():
    runtime = AgentsRuntime()
    with pytest.raises(ValueError, match="not found"):
        runtime._parse_llm_json('{"other_key": 1}', "scripts")


def test_parse_llm_json_array_response_raises():
    runtime = AgentsRuntime()
    with pytest.raises(ValueError, match="not a JSON object"):
        runtime._parse_llm_json("[1, 2, 3]", "scripts")


def test_parse_llm_json_non_string_input_raises():
    runtime = AgentsRuntime()
    with pytest.raises(ValueError, match="empty"):
        runtime._parse_llm_json(None, "scripts")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# run_video_scripting LLM integration tests
# ---------------------------------------------------------------------------


def test_video_scripting_llm_success_path_uses_parsed_json():
    """When LLM returns valid JSON, scripts come from the parsed output, not the template."""
    runtime = AgentsRuntime()

    llm_output = (
        '{"scripts": ['
        '{"variant_id": "V1", "hook": "LLM hook text", "script": "LLM script body", "shot_list": ["LLM shot 1", "LLM shot 2"]},'
        '{"variant_id": "V2", "hook": "Second hook", "script": "Second script", "shot_list": ["Shot A"]}'
        "]}"
    )
    runtime._chat_complete = lambda *args, **kwargs: (llm_output, "gpt-4.1", 0.05)

    variant_set = VariantSet(
        variants=[
            VariantCandidate(
                variant_id="V1",
                angle="template angle",
                hook="template hook",
                message="template message",
            )
        ]
    )
    intake = ProductIntake(
        product_name="test product",
        business_context={},
        asset_media_summary="Test summary.",
    )

    output = runtime.run_video_scripting(
        run_id="test-llm-success",
        variant_set=variant_set,
        intake=intake,
        business_context={
            "target_audience": "test audience",
            "key_value_props": ["test prop"],
            "primary_cta": "Buy Now",
        },
        provider="openai",
        model="gpt-4.1",
        creative_specs={},
        pipeline_mode=None,
    )

    assert output.model_used == "gpt-4.1"
    assert ":fallback_to_template" not in output.model_used
    scripts = output.payload["scripts"]
    assert len(scripts) == 2
    assert scripts[0]["variant_id"] == "V1"
    assert scripts[0]["hook"] == "LLM hook text"
    assert scripts[0]["script"] == "LLM script body"
    assert scripts[0]["shot_list"] == ["LLM shot 1", "LLM shot 2"]
    assert scripts[1]["variant_id"] == "V2"
    assert scripts[1]["hook"] == "Second hook"
    # Template-specific phrasing MUST NOT appear in LLM success path
    script_text_combined = " ".join(
        [scripts[0]["hook"], scripts[0]["script"], *scripts[0]["shot_list"]]
    ).lower()
    assert "variant hook:" not in script_text_combined
    assert "variant message:" not in script_text_combined


def test_video_scripting_llm_parse_failure_falls_back_to_template():
    """When LLM JSON is unparseable, fall back to template loop and tag model_used."""
    runtime = AgentsRuntime()
    runtime._chat_complete = lambda *args, **kwargs: ("not valid json", "gpt-4.1", 0.05)

    variant_set = VariantSet(
        variants=[
            VariantCandidate(
                variant_id="V1",
                angle="organized packing",
                hook="Pack faster",
                message="Keeps bottles upright.",
            )
        ]
    )
    intake = ProductIntake(
        product_name="travel toiletry bag",
        business_context={},
        asset_media_summary="Compact zip organizer.",
    )

    output = runtime.run_video_scripting(
        run_id="test-llm-fallback",
        variant_set=variant_set,
        intake=intake,
        business_context={
            "target_audience": "travelers",
            "key_value_props": ["keeps bottles upright"],
            "primary_cta": "Shop Now",
        },
        provider="openai",
        model="gpt-4.1",
        creative_specs={},
        pipeline_mode=None,
    )

    assert output.model_used == "gpt-4.1:fallback_to_template"
    scripts = output.payload["scripts"]
    assert len(scripts) == 1
    # Template content markers should appear
    script_text = " ".join(
        [scripts[0]["hook"], scripts[0]["script"], *scripts[0]["shot_list"]]
    ).lower()
    assert "variant hook:" in script_text or "variant message:" in script_text
    assert "travel toiletry bag" in script_text


def test_video_scripting_llm_empty_response_falls_back():
    """Empty LLM response triggers ValueError from _parse_llm_json and falls back."""
    runtime = AgentsRuntime()
    runtime._chat_complete = lambda *args, **kwargs: ("", "gpt-4.1", 0.05)

    variant_set = VariantSet(
        variants=[
            VariantCandidate(variant_id="V1", angle="test angle", hook="hook text", message="msg text")
        ]
    )
    intake = ProductIntake(
        product_name="widget",
        business_context={},
        asset_media_summary="A widget.",
    )

    output = runtime.run_video_scripting(
        run_id="test-empty-response",
        variant_set=variant_set,
        intake=intake,
        business_context={
            "target_audience": "buyers",
            "key_value_props": ["durable"],
            "primary_cta": "Buy",
        },
        provider="openai",
        model="gpt-4.1",
        creative_specs={},
        pipeline_mode=None,
    )

    assert ":fallback_to_template" in output.model_used
    assert len(output.payload["scripts"]) == 1
    assert output.payload["scripts"][0]["variant_id"] == "V1"


def test_video_scripting_llm_missing_scripts_key_falls_back():
    """LLM JSON without 'scripts' key falls back to template."""
    runtime = AgentsRuntime()
    runtime._chat_complete = lambda *args, **kwargs: ('{"other_key": [1,2,3]}', "gpt-4.1", 0.05)

    variant_set = VariantSet(
        variants=[
            VariantCandidate(variant_id="V1", angle="test angle", hook="hook text", message="msg text")
        ]
    )
    intake = ProductIntake(
        product_name="widget",
        business_context={},
        asset_media_summary="A widget.",
    )

    output = runtime.run_video_scripting(
        run_id="test-missing-key",
        variant_set=variant_set,
        intake=intake,
        business_context={
            "target_audience": "buyers",
            "key_value_props": ["durable"],
            "primary_cta": "Buy",
        },
        provider="openai",
        model="gpt-4.1",
        creative_specs={},
        pipeline_mode=None,
    )

    assert ":fallback_to_template" in output.model_used
    assert len(output.payload["scripts"]) == 1
    assert output.payload["scripts"][0]["variant_id"] == "V1"


def test_video_scripting_llm_success_path_populates_tiktok_payload():
    """When pipeline_mode is tiktok_shop_video and LLM succeeds, tiktok field must be populated."""
    runtime = AgentsRuntime()

    llm_output = (
        '{"scripts": ['
        '{"variant_id": "V1", "hook": "TikTok hook text", "script": "TikTok script body", "shot_list": ["TikTok shot 1", "TikTok shot 2"]}'
        "]}"
    )
    runtime._chat_complete = lambda *args, **kwargs: (llm_output, "gpt-4.1", 0.05)

    variant_set = VariantSet(
        variants=[
            VariantCandidate(
                variant_id="V1",
                angle="organized packing",
                hook="Pack faster without messy leaks",
                message="Keeps travel-size bottles upright and separated.",
            )
        ]
    )
    intake = ProductIntake(
        product_name="travel toiletry bag",
        business_context={},
        asset_media_summary="Compact zip organizer with clear compartments.",
    )

    output = runtime.run_video_scripting(
        run_id="test-tiktok-llm-success",
        variant_set=variant_set,
        intake=intake,
        business_context={
            "target_audience": "frequent travelers",
            "key_value_props": ["keeps bottles upright", "clear compartments"],
            "primary_cta": "Shop Now",
        },
        provider="openai",
        model="gpt-4.1",
        creative_specs={"tiktok_video_style": "ugc_demo", "video_duration_seconds": 12},
        pipeline_mode="tiktok_shop_video",
    )

    assert output.model_used == "gpt-4.1"
    assert ":fallback_to_template" not in output.model_used
    scripts = output.payload["scripts"]
    assert len(scripts) == 1
    assert scripts[0]["variant_id"] == "V1"
    assert scripts[0]["hook"] == "TikTok hook text"
    assert scripts[0]["script"] == "TikTok script body"
    assert scripts[0]["shot_list"] == ["TikTok shot 1", "TikTok shot 2"]

    # tiktok payload must be populated
    tiktok = scripts[0].get("tiktok")
    assert tiktok is not None, "tiktok field must be populated for tiktok_shop_video pipeline"
    assert isinstance(tiktok, dict)
    assert tiktok["style"] == "ugc_demo"
    assert "opening_hook" in tiktok
    assert isinstance(tiktok["on_screen_text"], list)
    assert isinstance(tiktok["voiceover_lines"], list)
    assert isinstance(tiktok["shot_timing"], list)
    assert isinstance(tiktok["product_proof_points"], list)
    assert tiktok["cta"] == "Shop Now"
    assert isinstance(tiktok["compliance_notes"], list)
    assert any("CTA intensity" in note for note in tiktok["compliance_notes"])


def test_tiktok_long_video_keeps_cta_to_final_seconds():
    runtime = AgentsRuntime()

    payload = runtime._build_tiktok_payload(
        product_name="olive satin dress",
        primary_value="one dress, three moods",
        cta="Shop the look",
        tiktok_style="direct_response_ad",
        video_duration=35,
    )

    cta_timing = payload["shot_timing"][-1]
    assert cta_timing["intent"] == "cta"
    assert cta_timing["end"] == 35
    assert cta_timing["end"] - cta_timing["start"] <= 4


# ---------------------------------------------------------------------------
# run_storyboard_image_generation LLM integration tests
# ---------------------------------------------------------------------------


def test_storyboard_llm_success_path_uses_llm_prompts():
    """When LLM returns valid JSON with frames, frame prompts come from the LLM output."""
    runtime = AgentsRuntime()

    llm_output = (
        '{"frames": ['
        '{"frame_id": "V1_F1", "variant_id": "V1", "prompt": "LLM storyboard prompt for frame 1"},'
        '{"frame_id": "V1_F2", "variant_id": "V1", "prompt": "LLM storyboard prompt for frame 2"},'
        '{"frame_id": "V1_F3", "variant_id": "V1", "prompt": "LLM storyboard prompt for frame 3"}'
        "]}"
    )
    runtime._chat_complete = lambda *args, **kwargs: (llm_output, "gpt-4.1", 0.05)

    def fake_generate_image(*, prompt, **kwargs):
        return (
            type("ImageResult", (), {"estimated_cost": 0.0, "images": []})(),
            "stub-image-provider",
            "stub-image-model",
        )

    runtime._generate_image = fake_generate_image

    script_pack = VideoScriptPack(
        scripts=[
            VideoScriptItem(
                variant_id="V1",
                hook="Pack faster without messy leaks",
                script="Show the travel toiletry bag holding upright bottles.",
                shot_list=[
                    "Open the bag on a hotel bathroom counter.",
                    "Close-up of upright bottle sleeves.",
                    "Packed bag slides neatly into a carry-on.",
                ],
            )
        ],
        product_context={"product_name": "travel toiletry bag", "audience": "frequent travelers"},
        generation_spec={"size": "16:9", "resolution": "720p", "duration": 5},
    )

    output = runtime.run_storyboard_image_generation(
        run_id="test-storyboard-llm-success",
        script_pack=script_pack,
        provider="openai",
        model="gpt-4.1",
        creative_specs={"video_size": "9:16"},
    )

    assert output.model_used == "gpt-4.1"
    assert ":fallback_to_template" not in output.model_used
    frames = output.payload["frames"]
    assert len(frames) == 3
    assert frames[0]["prompt"] == "LLM storyboard prompt for frame 1"
    assert frames[1]["prompt"] == "LLM storyboard prompt for frame 2"
    assert frames[2]["prompt"] == "LLM storyboard prompt for frame 3"
    # Template content must NOT appear in LLM success path
    assert "Create a realistic storyboard frame" not in frames[0]["prompt"]


def test_storyboard_llm_parse_failure_falls_back_to_template():
    """When LLM JSON is unparseable, fall back to template prompts and tag model_used."""
    runtime = AgentsRuntime()
    runtime._chat_complete = lambda *args, **kwargs: ("not valid json", "gpt-4.1", 0.05)

    def fake_generate_image(*, prompt, **kwargs):
        return (
            type("ImageResult", (), {"estimated_cost": 0.0, "images": []})(),
            "stub-image-provider",
            "stub-image-model",
        )

    runtime._generate_image = fake_generate_image

    script_pack = VideoScriptPack(
        scripts=[
            VideoScriptItem(
                variant_id="V1",
                hook="Pack faster without messy leaks",
                script="Show the travel toiletry bag holding upright bottles.",
                shot_list=[
                    "Open the bag on a hotel bathroom counter.",
                    "Close-up of upright bottle sleeves.",
                    "Packed bag slides neatly into a carry-on.",
                ],
            )
        ],
        product_context={"product_name": "travel toiletry bag", "audience": "frequent travelers"},
        generation_spec={"size": "16:9", "resolution": "720p", "duration": 5},
    )

    output = runtime.run_storyboard_image_generation(
        run_id="test-storyboard-llm-fallback",
        script_pack=script_pack,
        provider="openai",
        model="gpt-4.1",
        creative_specs={"video_size": "9:16"},
    )

    assert ":fallback_to_template" in output.model_used
    frames = output.payload["frames"]
    assert len(frames) == 3
    # Template content markers should appear in fallback path
    assert "Create a realistic storyboard frame" in frames[0]["prompt"]
    assert "travel toiletry bag" in frames[0]["prompt"].lower()


def test_storyboard_llm_empty_response_falls_back():
    """Empty LLM response triggers ValueError from _parse_llm_json and falls back."""
    runtime = AgentsRuntime()
    runtime._chat_complete = lambda *args, **kwargs: ("", "gpt-4.1", 0.05)

    def fake_generate_image(*, prompt, **kwargs):
        return (
            type("ImageResult", (), {"estimated_cost": 0.0, "images": []})(),
            "stub-image-provider",
            "stub-image-model",
        )

    runtime._generate_image = fake_generate_image

    script_pack = VideoScriptPack(
        scripts=[
            VideoScriptItem(
                variant_id="V1",
                hook="Hook text",
                script="Script body.",
                shot_list=["Shot 1", "Shot 2", "Shot 3"],
            )
        ],
        product_context={"product_name": "widget", "audience": "buyers"},
        generation_spec={},
    )

    output = runtime.run_storyboard_image_generation(
        run_id="test-storyboard-empty-response",
        script_pack=script_pack,
        provider="openai",
        model="gpt-4.1",
        creative_specs={"video_size": "9:16"},
    )

    assert ":fallback_to_template" in output.model_used
    assert len(output.payload["frames"]) == 3


def test_storyboard_llm_missing_frames_key_falls_back():
    """LLM JSON without 'frames' key falls back to template."""
    runtime = AgentsRuntime()
    runtime._chat_complete = lambda *args, **kwargs: ('{"other_key": [1,2,3]}', "gpt-4.1", 0.05)

    def fake_generate_image(*, prompt, **kwargs):
        return (
            type("ImageResult", (), {"estimated_cost": 0.0, "images": []})(),
            "stub-image-provider",
            "stub-image-model",
        )

    runtime._generate_image = fake_generate_image

    script_pack = VideoScriptPack(
        scripts=[
            VideoScriptItem(
                variant_id="V1",
                hook="Hook text",
                script="Script body.",
                shot_list=["Shot 1", "Shot 2", "Shot 3"],
            )
        ],
        product_context={"product_name": "widget", "audience": "buyers"},
        generation_spec={},
    )

    output = runtime.run_storyboard_image_generation(
        run_id="test-storyboard-missing-key",
        script_pack=script_pack,
        provider="openai",
        model="gpt-4.1",
        creative_specs={"video_size": "9:16"},
    )

    assert ":fallback_to_template" in output.model_used
    assert len(output.payload["frames"]) == 3
    assert "Create a realistic storyboard frame" in output.payload["frames"][0]["prompt"]


def test_storyboard_llm_partial_frame_match_uses_llm_for_match_fallback_for_miss():
    """When LLM returns some frames but not all, matched frames use LLM prompts, others use template."""
    runtime = AgentsRuntime()

    llm_output = (
        '{"frames": ['
        '{"frame_id": "V1_F1", "variant_id": "V1", "prompt": "LLM frame 1 prompt"},'
        '{"frame_id": "V1_F3", "variant_id": "V1", "prompt": "LLM frame 3 prompt"}'
        "]}"
    )
    runtime._chat_complete = lambda *args, **kwargs: (llm_output, "gpt-4.1", 0.05)

    def fake_generate_image(*, prompt, **kwargs):
        return (
            type("ImageResult", (), {"estimated_cost": 0.0, "images": []})(),
            "stub-image-provider",
            "stub-image-model",
        )

    runtime._generate_image = fake_generate_image

    script_pack = VideoScriptPack(
        scripts=[
            VideoScriptItem(
                variant_id="V1",
                hook="Hook text",
                script="Script body.",
                shot_list=["Shot 1", "Shot 2", "Shot 3"],
            )
        ],
        product_context={"product_name": "widget", "audience": "buyers"},
        generation_spec={},
    )

    output = runtime.run_storyboard_image_generation(
        run_id="test-storyboard-partial-match",
        script_pack=script_pack,
        provider="openai",
        model="gpt-4.1",
        creative_specs={"video_size": "9:16"},
    )

    assert output.model_used == "gpt-4.1"
    assert ":fallback_to_template" not in output.model_used
    frames = output.payload["frames"]
    assert len(frames) == 3
    # Frame 1 and 3 should use LLM prompts
    assert frames[0]["prompt"] == "LLM frame 1 prompt"
    assert frames[2]["prompt"] == "LLM frame 3 prompt"
    # Frame 2 should use template (fallback)
    assert "Create a realistic storyboard frame" in frames[1]["prompt"]


def test_storyboard_chat_complete_exception_still_uses_template():
    """When _chat_complete itself raises, inner parse is skipped and template is used."""
    runtime = AgentsRuntime()

    def failing_chat_complete(*args, **kwargs):
        raise RuntimeError("API transport failure")

    runtime._chat_complete = failing_chat_complete

    def fake_generate_image(*, prompt, **kwargs):
        return (
            type("ImageResult", (), {"estimated_cost": 0.0, "images": []})(),
            "stub-image-provider",
            "stub-image-model",
        )

    runtime._generate_image = fake_generate_image

    script_pack = VideoScriptPack(
        scripts=[
            VideoScriptItem(
                variant_id="V1",
                hook="Hook text",
                script="Script body.",
                shot_list=["Shot 1", "Shot 2", "Shot 3"],
            )
        ],
        product_context={"product_name": "widget", "audience": "buyers"},
        generation_spec={},
    )

    output = runtime.run_storyboard_image_generation(
        run_id="test-storyboard-transport-failure",
        script_pack=script_pack,
        provider="openai",
        model="gpt-4.1",
        creative_specs={"video_size": "9:16"},
    )

    assert ":storyboard_text_unavailable" in output.model_used
    assert ":fallback_to_template" not in output.model_used
    frames = output.payload["frames"]
    assert len(frames) == 3
    assert "Create a realistic storyboard frame" in frames[0]["prompt"]
    # Error should be set on frames
    assert frames[0]["error"] == "API transport failure"


# ---------------------------------------------------------------------------
# run_video_generation LLM integration tests
# ---------------------------------------------------------------------------


def test_video_generation_llm_success_path_uses_llm_prompts():
    """When LLM returns valid JSON with video_prompts, use LLM's prompt for video generation."""
    runtime = AgentsRuntime()

    llm_output = (
        '{"video_prompts": ['
        '{"variant_id": "V1", "prompt": "LLM optimized video prompt for V1", "quality_constraints": ["keep product centered"]},'
        '{"variant_id": "V2", "prompt": "LLM optimized video prompt for V2", "quality_constraints": ["maintain lighting consistency"]}'
        "]}"
    )
    runtime._chat_complete = lambda *args, **kwargs: (llm_output, "gpt-4.1", 0.05)

    fake_provider = _FakeVideoProvider()
    runtime.providers = _FakeRegistry(fake_provider)

    script_pack = VideoScriptPack(
        scripts=[
            VideoScriptItem(
                variant_id="V1",
                hook="Hook one",
                script="Script one.",
                shot_list=["Shot A", "Shot B"],
            ),
            VideoScriptItem(
                variant_id="V2",
                hook="Hook two",
                script="Script two.",
                shot_list=["Shot C", "Shot D"],
            ),
        ],
        product_context={"product_name": "test product", "audience": "testers"},
        generation_spec={"size": "16:9", "resolution": "720p", "duration": 5},
    )

    output = runtime.run_video_generation(
        run_id="test-video-gen-llm-success",
        script_pack=script_pack,
        creative_specs={},
        provider="apimart",
        model="doubao-seedance-2.0",
    )

    assert ":fallback_to_template" not in output.model_used
    assert "text=gpt-4.1" in output.model_used
    videos = output.payload["videos"]
    assert len(videos) == 2
    # V1 should use LLM prompt
    assert videos[0]["prompt"] == "LLM optimized video prompt for V1"
    assert videos[0]["variant_id"] == "V1"
    # V2 should use LLM prompt
    assert videos[1]["prompt"] == "LLM optimized video prompt for V2"
    assert videos[1]["variant_id"] == "V2"
    # Template-specific phrasing MUST NOT appear in LLM success path
    assert "Generate a short social ad video clip based on script" not in videos[0]["prompt"]


def test_video_generation_llm_parse_failure_falls_back_to_template():
    """When LLM JSON is unparseable, fall back to template prompts and tag model_used."""
    runtime = AgentsRuntime()
    runtime._chat_complete = lambda *args, **kwargs: ("not valid json", "gpt-4.1", 0.05)

    fake_provider = _FakeVideoProvider()
    runtime.providers = _FakeRegistry(fake_provider)

    script_pack = VideoScriptPack(
        scripts=[
            VideoScriptItem(
                variant_id="V1",
                hook="Pack faster without messy leaks",
                script="Show the travel toiletry bag holding upright bottles.",
                shot_list=["Open the bag", "Close-up of bottles", "Slide into carry-on"],
            )
        ],
        product_context={"product_name": "travel toiletry bag", "audience": "frequent travelers"},
        generation_spec={"size": "16:9", "resolution": "720p", "duration": 5},
    )

    output = runtime.run_video_generation(
        run_id="test-video-gen-llm-fallback",
        script_pack=script_pack,
        creative_specs={},
        provider="apimart",
        model="doubao-seedance-2.0",
    )

    assert ":fallback_to_template" in output.model_used
    videos = output.payload["videos"]
    assert len(videos) == 1
    # Template content markers should appear in fallback path
    assert "Generate a short social ad video clip based on script" in videos[0]["prompt"]
    assert "travel toiletry bag" in videos[0]["prompt"].lower()


def test_video_generation_continues_when_prompt_llm_fails():
    runtime = AgentsRuntime()

    def fail_chat(*args, **kwargs):
        raise RuntimeError("text model unavailable")

    runtime._chat_complete = fail_chat
    fake_provider = _FakeVideoProvider()
    runtime.providers = _FakeRegistry(fake_provider)

    script_pack = VideoScriptPack(
        scripts=[
            VideoScriptItem(
                variant_id="V1",
                hook="Hook text",
                script="Script body.",
                shot_list=["Shot 1", "Shot 2"],
            )
        ],
        product_context={"product_name": "test product", "audience": "testers"},
        generation_spec={"size": "16:9", "resolution": "720p", "duration": 5},
    )

    output = runtime.run_video_generation(
        run_id="test-video-gen-text-fallback",
        script_pack=script_pack,
        storyboard_frames=None,
        creative_specs={},
        provider="deepseek",
        model="deepseek-v4-pro",
        runtime_config={"video": {"provider_name": "apimart", "model_name": "doubao-seedance-2.0"}},
    )

    assert fake_provider.last_request is not None
    assert "text=deepseek-v4-pro:fallback_to_template" in output.model_used
    assert "video=doubao-seedance-2.0" in output.model_used
    assert output.payload["videos"][0]["generation_status"] == "submitted"


def test_video_generation_storyboard_frames_inject_image_urls():
    """storyboard_frames image_uri values are converted to data URLs and injected into generation_spec."""
    import base64
    import os
    import tempfile

    runtime = AgentsRuntime()
    runtime._chat_complete = lambda *args, **kwargs: ("ok", "stub-model", 0.0)

    fake_provider = _FakeVideoProvider()
    runtime.providers = _FakeRegistry(fake_provider)

    # Create a real temporary image file
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        tmp_path = tmp.name

    try:
        storyboard_frames = [
            {"frame_id": "V1_F1", "variant_id": "V1", "image_uri": tmp_path, "prompt": "frame prompt"},
        ]

        script_pack = VideoScriptPack(
            scripts=[
                VideoScriptItem(
                    variant_id="V1",
                    hook="Hook text",
                    script="Script body.",
                    shot_list=["Shot 1", "Shot 2"],
                )
            ],
            product_context={"product_name": "test product", "audience": "testers"},
            generation_spec={"size": "16:9", "resolution": "720p", "duration": 5},
        )

        output = runtime.run_video_generation(
            run_id="test-video-gen-storyboard-inject",
            script_pack=script_pack,
            storyboard_frames=storyboard_frames,
            creative_specs={},
            provider="apimart",
            model="doubao-seedance-2.0",
        )

        # The generation_spec should contain image_urls with the data URL
        video_payload = output.payload["videos"][0]
        gen_spec = video_payload.get("generation_spec", {})
        image_urls = gen_spec.get("image_urls", [])
        assert len(image_urls) >= 1
        data_url = image_urls[0]
        assert data_url.startswith("data:image/png;base64,")
        # Verify it's a valid base64 data URL
        b64_part = data_url.split(",", 1)[1]
        decoded = base64.b64decode(b64_part)
        assert len(decoded) > 0
    finally:
        os.unlink(tmp_path)


def test_video_generation_storyboard_frames_prefer_provider_urls():
    runtime = AgentsRuntime()
    runtime._chat_complete = lambda *args, **kwargs: ("ok", "stub-model", 0.0)

    fake_provider = _FakeVideoProvider()
    runtime.providers = _FakeRegistry(fake_provider)

    storyboard_frames = [
        {
            "frame_id": "V1_F1",
            "variant_id": "V1",
            "image_uri": "/nonexistent/local-copy.png",
            "raw_response": {"data": [{"url": "https://getapib.org/tokens/storyboard-frame.png"}]},
        },
    ]
    script_pack = VideoScriptPack(
        scripts=[
            VideoScriptItem(
                variant_id="V1",
                hook="Hook text",
                script="Script body.",
                shot_list=["Shot 1", "Shot 2"],
            )
        ],
        product_context={"product_name": "test product", "audience": "testers"},
        generation_spec={"size": "16:9", "resolution": "720p", "duration": 5},
    )

    output = runtime.run_video_generation(
        run_id="test-video-gen-storyboard-provider-url",
        script_pack=script_pack,
        storyboard_frames=storyboard_frames,
        creative_specs={},
        provider="apimart",
        model="doubao-seedance-2.0",
    )

    video_payload = output.payload["videos"][0]
    assert video_payload["generation_spec"]["image_urls"] == ["https://getapib.org/tokens/storyboard-frame.png"]


def test_video_generation_storyboard_frames_none_unchanged():
    """When storyboard_frames is None, image_urls from creative_specs are preserved unchanged."""
    runtime = AgentsRuntime()
    runtime._chat_complete = lambda *args, **kwargs: ("ok", "stub-model", 0.0)

    fake_provider = _FakeVideoProvider()
    runtime.providers = _FakeRegistry(fake_provider)

    script_pack = VideoScriptPack(
        scripts=[
            VideoScriptItem(
                variant_id="V1",
                hook="Hook text",
                script="Script body.",
                shot_list=["Shot 1", "Shot 2"],
            )
        ],
        product_context={"product_name": "test product", "audience": "testers"},
        generation_spec={"size": "16:9", "resolution": "720p", "duration": 5},
    )

    output = runtime.run_video_generation(
        run_id="test-video-gen-no-storyboard",
        script_pack=script_pack,
        creative_specs={
            "image_urls": ["https://example.com/reference-image.png"],
        },
        provider="apimart",
        model="doubao-seedance-2.0",
    )

    # The generation_spec should contain only the creative_specs image_urls
    video_payload = output.payload["videos"][0]
    gen_spec = video_payload.get("generation_spec", {})
    image_urls = gen_spec.get("image_urls", [])
    assert image_urls == ["https://example.com/reference-image.png"]


def test_video_generation_storyboard_frame_file_missing_skipped():
    """storyboard_frames with non-existent image_uri paths are skipped, not injected."""
    runtime = AgentsRuntime()
    runtime._chat_complete = lambda *args, **kwargs: ("ok", "stub-model", 0.0)

    fake_provider = _FakeVideoProvider()
    runtime.providers = _FakeRegistry(fake_provider)

    storyboard_frames = [
        {"frame_id": "V1_F1", "variant_id": "V1", "image_uri": "/nonexistent/path/frame.png", "prompt": "frame prompt"},
    ]

    script_pack = VideoScriptPack(
        scripts=[
            VideoScriptItem(
                variant_id="V1",
                hook="Hook text",
                script="Script body.",
                shot_list=["Shot 1", "Shot 2"],
            )
        ],
        product_context={"product_name": "test product", "audience": "testers"},
        generation_spec={"size": "16:9", "resolution": "720p", "duration": 5},
    )

    output = runtime.run_video_generation(
        run_id="test-video-gen-frame-missing",
        script_pack=script_pack,
        storyboard_frames=storyboard_frames,
        creative_specs={
            "image_urls": ["https://example.com/reference-image.png"],
        },
        provider="apimart",
        model="doubao-seedance-2.0",
    )

    # The generation_spec should only retain the creative_specs image_urls
    # (the missing frame file was skipped by _local_image_to_data_url)
    video_payload = output.payload["videos"][0]
    gen_spec = video_payload.get("generation_spec", {})
    image_urls = gen_spec.get("image_urls", [])
    assert image_urls == ["https://example.com/reference-image.png"]

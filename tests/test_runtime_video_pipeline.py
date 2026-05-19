from __future__ import annotations

import pytest

from app.agents.runtime import AgentsRuntime
from app.providers.llm import GeneratedVideo, VideoGenResult
from app.schemas.contracts import ProductIntake, VariantCandidate, VariantSet, VideoScriptItem, VideoScriptPack


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


class _FakeRegistry:
    def __init__(self, provider) -> None:
        self.provider = provider

    def get(self, _provider_name: str):
        return self.provider


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

from __future__ import annotations

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

import pytest


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


def test_parse_llm_json_fence_without_json_tag():
    runtime = AgentsRuntime()
    result = runtime._parse_llm_json(
        '```\n{"video_prompts": [{"id": "v1"}]}\n```',
        "video_prompts",
    )
    assert result == {"video_prompts": [{"id": "v1"}]}

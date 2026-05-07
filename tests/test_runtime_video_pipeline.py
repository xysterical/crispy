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
    assert fake_provider.last_extra is not None
    assert fake_provider.last_extra["video_payload"]["generate_audio"] is True
    assert fake_provider.last_extra["video_payload"]["return_last_frame"] is True
    assert fake_provider.last_extra["video_payload"]["seed"] == 42
    assert fake_provider.last_extra["video_payload"]["tools"] == [{"type": "web_search"}]
    assert fake_provider.last_extra["video_payload"]["image_urls"] == ["https://example.com/reference-image.png"]
    assert fake_provider.last_extra["video_payload"]["audio_urls"] == ["https://example.com/reference-audio.wav"]

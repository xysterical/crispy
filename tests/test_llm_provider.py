from __future__ import annotations

import httpx

from app.providers.llm import ImageGenRequest, MultimodalChatRequest, OpenAICompatibleProvider, ProviderRequestError, VideoGenRequest


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://example.com")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("http error", request=request, response=response)

    def json(self) -> dict:
        return self._payload


class _FakeStreamResponse:
    def __init__(self, status_code: int, lines: list[str]):
        self.status_code = status_code
        self._lines = lines
        self.text = "\n".join(lines)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def iter_lines(self):
        return iter(self._lines)


class _FakeClient:
    def __init__(
        self,
        post_map: dict[str, _FakeResponse],
        get_map: dict[str, _FakeResponse] | None = None,
        stream_map: dict[str, _FakeStreamResponse] | None = None,
        timeout: float = 0.0,
    ):
        self.post_map = post_map
        self.get_map = get_map or {}
        self.stream_map = stream_map or {}
        self.timeout = timeout
        self.posted_urls: list[str] = []
        self.got_urls: list[str] = []
        self.streamed_urls: list[str] = []
        self.posted_json_by_url: dict[str, dict] = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def post(self, url: str, json: dict, headers: dict) -> _FakeResponse:
        self.posted_urls.append(url)
        self.posted_json_by_url[url] = json
        return self.post_map.get(url, _FakeResponse(404, {"error": "not_found"}))

    def get(self, url: str, headers: dict | None = None) -> _FakeResponse:
        self.got_urls.append(url)
        return self.get_map.get(url, _FakeResponse(404, {"error": "not_found"}))

    def stream(self, method: str, url: str, json: dict, headers: dict):
        self.streamed_urls.append(url)
        self.posted_json_by_url[url] = json
        return self.stream_map.get(url, _FakeStreamResponse(404, ['{"error":"not_found"}']))


def test_chat_complete_falls_back_to_stub_without_credentials():
    provider = OpenAICompatibleProvider("openai")
    result = provider.chat_complete(MultimodalChatRequest(prompt="hello world", model="gpt-4.1"))
    assert "hello world" in result.text
    assert result.model_used == "gpt-4.1"


def test_chat_complete_endpoint_fallback_to_v1(monkeypatch):
    client = _FakeClient(
        post_map={
            "https://api-xai.ainaibahub.com/chat/completions": _FakeResponse(404, {"error": "missing"}),
            "https://api-xai.ainaibahub.com/v1/chat/completions": _FakeResponse(
                200,
                {
                    "model": "gpt-5.4",
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                },
            ),
        }
    )
    monkeypatch.setattr("app.providers.llm.httpx.Client", lambda timeout=90.0: setattr(client, "timeout", timeout) or client)
    provider = OpenAICompatibleProvider("xai")
    result = provider.chat_complete(
        MultimodalChatRequest(prompt="ping", model="gpt-5.4"),
        api_base_url="https://api-xai.ainaibahub.com",
        api_key="dummy",
    )
    assert result.text == "ok"
    assert result.tokens_prompt == 10
    assert client.posted_urls[0].endswith("/chat/completions")
    assert client.posted_urls[1].endswith("/v1/chat/completions")


def test_chat_complete_stream_openai_compatible(monkeypatch):
    endpoint = "https://api.example.com/v1/chat/completions"
    client = _FakeClient(
        post_map={},
        stream_map={
            endpoint: _FakeStreamResponse(
                200,
                [
                    'data: {"choices":[{"delta":{"content":"hel"}}]}',
                    'data: {"choices":[{"delta":{"content":"lo"}}]}',
                    "data: [DONE]",
                ],
            )
        },
    )
    monkeypatch.setattr("app.providers.llm.httpx.Client", lambda timeout=90.0: setattr(client, "timeout", timeout) or client)
    provider = OpenAICompatibleProvider("openai")
    events = list(
        provider.chat_complete_stream(
            MultimodalChatRequest(prompt="ping", model="gpt-4.1"),
            api_base_url="https://api.example.com/v1",
            api_key="dummy",
        )
    )
    assert [event.text for event in events if event.type == "text_delta"] == ["hel", "lo"]
    assert events[-1].type == "completed"
    assert client.posted_json_by_url[endpoint]["stream"] is True


def test_chat_complete_multimodal_with_video_url(monkeypatch):
    endpoint = "https://api.moonshot.cn/v1/chat/completions"
    client = _FakeClient(
        post_map={
            endpoint: _FakeResponse(
                200,
                {
                    "model": "kimi-k2.6",
                    "choices": [{"message": {"content": "media ok"}}],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 4},
                },
            )
        }
    )
    monkeypatch.setattr("app.providers.llm.httpx.Client", lambda timeout=90.0: setattr(client, "timeout", timeout) or client)
    provider = OpenAICompatibleProvider("kimi")
    result = provider.chat_complete(
        MultimodalChatRequest(
            prompt="请描述上传的图片和视频",
            model="kimi-k2.6",
            image_urls=["data:image/png;base64,AAAA"],
            video_urls=["data:video/mp4;base64,BBBB"],
        ),
        api_base_url="https://api.moonshot.cn/v1",
        api_key="dummy",
    )
    assert result.text == "media ok"
    payload = client.posted_json_by_url[endpoint]
    assert payload["model"] == "kimi-k2.6"
    content = payload["messages"][0]["content"]
    assert content[0]["type"] == "text"
    assert any(part.get("type") == "image_url" for part in content)
    assert any(part.get("type") == "video_url" for part in content)


def test_chat_complete_kimi_thinking_disabled_and_max_tokens(monkeypatch):
    endpoint = "https://api.moonshot.cn/v1/chat/completions"
    client = _FakeClient(
        post_map={
            endpoint: _FakeResponse(
                200,
                {
                    "model": "kimi-k2.6",
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                },
            )
        }
    )
    monkeypatch.setattr("app.providers.llm.httpx.Client", lambda timeout=90.0: setattr(client, "timeout", timeout) or client)
    provider = OpenAICompatibleProvider("kimi")
    result = provider.chat_complete(
        MultimodalChatRequest(prompt="ping", model="kimi-k2.6"),
        api_base_url="https://api.moonshot.cn/v1",
        api_key="dummy",
        extra={"thinking_mode": "disabled", "max_output_tokens": 1200, "request_timeout_seconds": 30},
    )
    assert result.text == "ok"
    payload = client.posted_json_by_url[endpoint]
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["max_tokens"] == 1200
    assert "temperature" not in payload
    assert client.timeout == 30


def test_chat_complete_thinking_auto_does_not_force_payload(monkeypatch):
    endpoint = "https://api.moonshot.cn/v1/chat/completions"
    client = _FakeClient(
        post_map={
            endpoint: _FakeResponse(
                200,
                {
                    "model": "kimi-k2.6",
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                },
            )
        }
    )
    monkeypatch.setattr("app.providers.llm.httpx.Client", lambda timeout=90.0: client)
    OpenAICompatibleProvider("kimi").chat_complete(
        MultimodalChatRequest(prompt="ping", model="kimi-k2.6"),
        api_base_url="https://api.moonshot.cn/v1",
        api_key="dummy",
        extra={"thinking_mode": "auto"},
    )
    assert "thinking" not in client.posted_json_by_url[endpoint]


def test_generate_image_uses_full_endpoint_without_extra_append(monkeypatch):
    endpoint = "https://api.apimart.ai/v1/images/generations"
    client = _FakeClient(
        post_map={
            endpoint: _FakeResponse(
                200,
                {
                    "model": "gpt-image-2",
                    "data": [{"b64_json": "aGVsbG8=", "revised_prompt": "ok prompt"}],
                },
            )
        }
    )
    monkeypatch.setattr("app.providers.llm.httpx.Client", lambda timeout=90.0: client)
    provider = OpenAICompatibleProvider("apimart")
    result = provider.generate_image(
        ImageGenRequest(model="gpt-image-2", prompt="dog leash", size="1:1"),
        api_base_url=endpoint,
        api_key="dummy",
    )
    assert len(result.images) == 1
    assert result.images[0].b64_json == "aGVsbG8="
    assert client.posted_urls == [endpoint]


def test_generate_image_async_task_polling(monkeypatch):
    endpoint = "https://api.apimart.ai/v1/images/generations"
    task_id = "task_123"
    status_url = f"https://api.apimart.ai/v1/tasks/{task_id}?language=en"
    client = _FakeClient(
        post_map={
            endpoint: _FakeResponse(
                200,
                {"code": 200, "data": [{"status": "submitted", "task_id": task_id}]},
            )
        },
        get_map={
            status_url: _FakeResponse(
                200,
                {
                    "code": 200,
                    "data": {
                        "status": "completed",
                        "result": {"image_url": "https://example.com/image.png"},
                    },
                },
            )
        },
    )
    monkeypatch.setattr("app.providers.llm.httpx.Client", lambda timeout=90.0: client)
    monkeypatch.setattr("app.providers.llm.time.sleep", lambda _: None)
    provider = OpenAICompatibleProvider("apimart")
    result = provider.generate_image(
        ImageGenRequest(model="gpt-image-2", prompt="dog leash", size="1:1"),
        api_base_url=endpoint,
        api_key="dummy",
    )
    assert len(result.images) == 1
    assert result.images[0].url == "https://example.com/image.png"


def test_image_task_status_candidates_use_generation_root():
    provider = OpenAICompatibleProvider("apimart")

    candidates = provider._task_status_candidates(
        "https://api.apimart.ai/v1/images/generations",
        "task_123",
    )

    assert candidates == ["https://api.apimart.ai/v1/tasks/task_123?language=en"]


def test_generate_image_pending_task_does_not_return_placeholder(monkeypatch):
    endpoint = "https://api.apimart.ai/v1/images/generations"
    task_id = "task_pending"
    status_url = f"https://api.apimart.ai/v1/tasks/{task_id}?language=en"
    client = _FakeClient(
        post_map={
            endpoint: _FakeResponse(
                200,
                {"code": 200, "data": [{"status": "submitted", "task_id": task_id}]},
            )
        },
        get_map={status_url: _FakeResponse(200, {"code": 200, "data": {"status": "processing"}})},
    )
    monkeypatch.setattr("app.providers.llm.httpx.Client", lambda timeout=90.0: client)
    monkeypatch.setattr("app.providers.llm.time.sleep", lambda _: None)
    provider = OpenAICompatibleProvider("apimart")

    try:
        provider.generate_image(
            ImageGenRequest(model="gpt-image-2", prompt="raincoat", size="1:1"),
            api_base_url=endpoint,
            api_key="dummy",
            extra={"image_poll_max_wait_seconds": -1},
        )
    except ProviderRequestError as exc:
        assert f"provider image task {task_id} returned no image data" in str(exc)
        assert exc.errors[0]["task_id"] == task_id
    else:
        raise AssertionError("expected pending task to fail with provider evidence")


def test_generate_image_submit_only_returns_task_without_polling(monkeypatch):
    endpoint = "https://api.apimart.ai/v1/images/generations"
    client = _FakeClient(
        post_map={
            endpoint: _FakeResponse(
                200,
                {"model": "gpt-image-2", "data": [{"status": "submitted", "task_id": "task_image_submit"}]},
            )
        },
        get_map={
            "https://api.apimart.ai/v1/tasks/task_image_submit?language=en": _FakeResponse(
                200,
                {"data": {"status": "completed", "result": {"image_url": "https://example.com/image.png"}}},
            )
        },
    )
    monkeypatch.setattr("app.providers.llm.httpx.Client", lambda timeout=90.0: client)
    provider = OpenAICompatibleProvider("apimart")
    result = provider.generate_image(
        ImageGenRequest(model="gpt-image-2", prompt="robe storyboard", size="9:16"),
        api_base_url=endpoint,
        api_key="dummy",
        extra={"submit_only": True},
    )
    assert result.task_id == "task_image_submit"
    assert result.images[0].task_id == "task_image_submit"
    assert client.got_urls == []


def test_generate_image_apimart_payload_uses_documented_fields(monkeypatch):
    endpoint = "https://api.apimart.ai/v1/images/generations"
    client = _FakeClient(
        post_map={
            endpoint: _FakeResponse(
                200,
                {"code": 200, "data": [{"status": "submitted", "task_id": "task_image_payload"}]},
            )
        },
        get_map={
            "https://api.apimart.ai/v1/tasks/task_image_payload?language=en": _FakeResponse(
                200,
                {
                    "code": 200,
                    "data": {
                        "status": "completed",
                        "result": {
                            "images": [
                                {"url": ["https://example.com/image_from_task.png"]},
                            ]
                        },
                    },
                },
            )
        },
    )
    monkeypatch.setattr("app.providers.llm.httpx.Client", lambda timeout=90.0: client)
    monkeypatch.setattr("app.providers.llm.time.sleep", lambda _: None)
    provider = OpenAICompatibleProvider("apimart")
    result = provider.generate_image(
        ImageGenRequest(
            model="gpt-image-2",
            prompt="travel pouch hero shot",
            size="16:9",
            image_urls=[
                "https://example.com/reference-a.png",
                "data:image/png;base64,AAAA",
            ],
            official_fallback=True,
        ),
        api_base_url=endpoint,
        api_key="dummy",
    )
    assert result.images[0].url == "https://example.com/image_from_task.png"
    sent = client.posted_json_by_url[endpoint]
    assert sent["image_urls"] == [
        "https://example.com/reference-a.png",
        "data:image/png;base64,AAAA",
    ]
    assert sent["official_fallback"] is True
    assert "reference_image_urls" not in sent


def test_generate_image_rejects_invalid_apimart_request_locally(monkeypatch):
    endpoint = "https://api.apimart.ai/v1/images/generations"
    client = _FakeClient(post_map={})
    monkeypatch.setattr("app.providers.llm.httpx.Client", lambda timeout=90.0: client)
    provider = OpenAICompatibleProvider("apimart")

    for request, expected_error in [
        (
            ImageGenRequest(model="gpt-image-2", prompt="x", n=2, size="1:1"),
            "n must be 1",
        ),
        (
            ImageGenRequest(model="gpt-image-2", prompt="x", size="1024x1024"),
            "size must be one of",
        ),
        (
            ImageGenRequest(
                model="gpt-image-2",
                prompt="x",
                image_urls=[f"https://example.com/{idx}.png" for idx in range(17)],
            ),
            "image_urls supports at most 16",
        ),
    ]:
        try:
            provider.generate_image(request, api_base_url=endpoint, api_key="dummy")
        except ValueError as exc:
            assert expected_error in str(exc)
        else:
            raise AssertionError("expected local request validation error")
    assert client.posted_urls == []


def test_generate_video_uses_configured_endpoint(monkeypatch):
    endpoint = "https://api.video-provider.ai/v1/videos/generations"
    client = _FakeClient(
        post_map={
            endpoint: _FakeResponse(
                200,
                {
                    "model": "doubao-seedance-2.0",
                    "data": [{"video_url": "https://example.com/video.mp4"}],
                },
            )
        }
    )
    monkeypatch.setattr("app.providers.llm.httpx.Client", lambda timeout=90.0: client)
    provider = OpenAICompatibleProvider("custom")
    result = provider.generate_video(
        VideoGenRequest(model="doubao-seedance-2.0", prompt="dog leash in park", size="9:16"),
        api_base_url=endpoint,
        api_key="dummy",
    )
    assert len(result.videos) == 1
    assert result.videos[0].url == "https://example.com/video.mp4"
    assert client.posted_urls == [endpoint]
    sent = client.posted_json_by_url[endpoint]
    assert sent["duration"] == 8
    assert sent["resolution"] == "720p"
    assert "duration_seconds" not in sent


def test_generate_video_apimart_payload_uses_typed_structured_fields(monkeypatch):
    endpoint = "https://api.apimart.ai/v1/videos/generations"
    client = _FakeClient(
        post_map={
            endpoint: _FakeResponse(
                200,
                {
                    "model": "doubao-seedance-2.0",
                    "data": [{"video_url": "https://example.com/typed-structured-video.mp4"}],
                },
            )
        }
    )
    monkeypatch.setattr("app.providers.llm.httpx.Client", lambda timeout=90.0: client)
    provider = OpenAICompatibleProvider("apimart")
    result = provider.generate_video(
        VideoGenRequest(
            model="doubao-seedance-2.0",
            prompt="show the travel bag opening and closing",
            size="16:9",
            resolution="720p",
            duration_seconds=5,
            generate_audio=True,
            return_last_frame=True,
            seed=42,
            tools=[{"type": "web_search"}],
            image_urls=["https://example.com/frame-1.png"],
            audio_urls=["https://example.com/music.wav"],
        ),
        api_base_url=endpoint,
        api_key="dummy",
    )
    assert result.videos[0].url == "https://example.com/typed-structured-video.mp4"
    sent = client.posted_json_by_url[endpoint]
    assert sent["generate_audio"] is True
    assert sent["return_last_frame"] is True
    assert sent["seed"] == 42
    assert sent["tools"] == [{"type": "web_search"}]
    assert sent["image_urls"] == ["https://example.com/frame-1.png"]
    assert sent["audio_urls"] == ["https://example.com/music.wav"]


def test_generate_video_rejects_invalid_seedance_request_locally(monkeypatch):
    endpoint = "https://api.apimart.ai/v1/videos/generations"
    client = _FakeClient(post_map={})
    monkeypatch.setattr("app.providers.llm.httpx.Client", lambda timeout=90.0: client)
    provider = OpenAICompatibleProvider("apimart")

    invalid_requests = [
        (
            VideoGenRequest(model="doubao-seedance-2.0", prompt="x", duration_seconds=3),
            "duration must be between 4 and 15",
        ),
        (
            VideoGenRequest(
                model="doubao-seedance-2.0",
                prompt="x",
                image_urls=["https://example.com/a.png"],
                image_with_roles=[{"url": "https://example.com/b.png", "role": "first_frame"}],
            ),
            "image_urls and image_with_roles cannot both be set",
        ),
        (
            VideoGenRequest(
                model="doubao-seedance-2.0",
                image_with_roles=[{"url": "https://example.com/a.png", "role": "first_frame"}],
                video_urls=["https://example.com/ref.mp4"],
            ),
            "video_urls and audio_urls are incompatible with image_with_roles",
        ),
        (
            VideoGenRequest(
                model="doubao-seedance-2.0",
                image_with_roles=[{"url": "https://example.com/a.png", "role": "first_frame"}],
                audio_urls=["https://example.com/ref.wav"],
            ),
            "video_urls and audio_urls are incompatible with image_with_roles",
        ),
        (
            VideoGenRequest(
                model="doubao-seedance-2.0",
                image_urls=["data:image/png;base64,AAAA"],
            ),
            "image_urls only supports http/https or asset:// references",
        ),
        (
            VideoGenRequest(
                model="doubao-seedance-2.0",
                image_with_roles=[{"url": "/tmp/local-frame.png", "role": "first_frame"}],
            ),
            "image_with_roles.url only supports http/https or asset:// references",
        ),
    ]
    for request, expected_error in invalid_requests:
        try:
            provider.generate_video(request, api_base_url=endpoint, api_key="dummy")
        except ValueError as exc:
            assert expected_error in str(exc)
        else:
            raise AssertionError("expected local request validation error")
    assert client.posted_urls == []


def test_generate_video_async_task_polling_and_alias(monkeypatch):
    endpoint = "https://api.apimart.ai/v1/videos/generations"
    task_id = "task_video_001"
    status_url = f"https://api.apimart.ai/v1/tasks/{task_id}?language=en"
    client = _FakeClient(
        post_map={
            endpoint: _FakeResponse(
                200,
                {"code": 200, "data": [{"status": "submitted", "task_id": task_id}]},
            )
        },
        get_map={
            status_url: _FakeResponse(
                200,
                {
                    "code": 200,
                    "data": {
                        "status": "completed",
                        "result": {
                            "videos": [
                                {
                                    "url": ["https://example.com/video_from_task.mp4"],
                                    "last_frame_url": "https://example.com/video_last_frame.png",
                                },
                            ]
                        },
                    },
                },
            )
        },
    )
    monkeypatch.setattr("app.providers.llm.httpx.Client", lambda timeout=90.0: client)
    monkeypatch.setattr("app.providers.llm.time.sleep", lambda _: None)
    provider = OpenAICompatibleProvider("apimart")
    result = provider.generate_video(
        VideoGenRequest(
            model="douban-seedance-2-0",
            prompt="dog leash in park",
            size="9:16",
            duration_seconds=5,
            resolution="720p",
        ),
        api_base_url=endpoint,
        api_key="dummy",
    )
    assert len(result.videos) == 1
    assert result.videos[0].url == "https://example.com/video_from_task.mp4"
    assert result.videos[0].raw_response["last_frame_url"] == "https://example.com/video_last_frame.png"
    sent = client.posted_json_by_url[endpoint]
    assert sent["model"] == "doubao-seedance-2.0"
    assert sent["duration"] == 5
    assert sent["size"] == "9:16"
    assert sent["resolution"] == "720p"


def test_generate_video_submit_only_returns_task_id_without_polling(monkeypatch):
    endpoint = "https://api.apimart.ai/v1/videos/generations"
    task_id = "task_video_submit"
    client = _FakeClient(
        post_map={
            endpoint: _FakeResponse(
                200,
                {"code": 200, "data": [{"status": "submitted", "task_id": task_id}]},
            )
        }
    )
    monkeypatch.setattr("app.providers.llm.httpx.Client", lambda timeout=90.0: client)
    provider = OpenAICompatibleProvider("apimart")
    result = provider.generate_video(
        VideoGenRequest(model="doubao-seedance-2.0", prompt="dog leash", size="9:16"),
        api_base_url=endpoint,
        api_key="dummy",
        extra={"submit_only": True},
    )
    assert result.task_id == task_id
    assert result.status == "submitted"
    assert result.videos[0].task_id == task_id
    assert client.got_urls == []


def test_provider_error_includes_endpoint_status_and_body(monkeypatch):
    endpoint = "https://api.example.com/v1/chat/completions"
    client = _FakeClient(post_map={endpoint: _FakeResponse(500, {"error": {"message": "boom", "traceid": "abc"}})})
    monkeypatch.setattr("app.providers.llm.httpx.Client", lambda timeout=90.0: client)
    provider = OpenAICompatibleProvider("custom")
    try:
        provider.chat_complete(
            MultimodalChatRequest(prompt="ping", model="model"),
            api_base_url="https://api.example.com/v1",
            api_key="dummy",
        )
    except Exception as exc:
        assert "request failed for all endpoint candidates" in str(exc)
        assert getattr(exc, "errors")[0]["status_code"] == 500
        assert "traceid" in getattr(exc, "errors")[0]["body"]
    else:
        raise AssertionError("expected provider error")

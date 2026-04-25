from __future__ import annotations

import httpx

from app.providers.llm import ImageGenRequest, MultimodalChatRequest, OpenAICompatibleProvider, VideoGenRequest


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


class _FakeClient:
    def __init__(self, post_map: dict[str, _FakeResponse], get_map: dict[str, _FakeResponse] | None = None, timeout: float = 0.0):
        self.post_map = post_map
        self.get_map = get_map or {}
        self.timeout = timeout
        self.posted_urls: list[str] = []
        self.got_urls: list[str] = []
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
                                {"url": ["https://example.com/video_from_task.mp4"]},
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

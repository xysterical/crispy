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
    monkeypatch.setattr("app.providers.llm.httpx.Client", lambda timeout=90.0: client)
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

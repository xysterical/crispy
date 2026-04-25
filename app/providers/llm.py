from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from typing import Any

import httpx


_PLACEHOLDER_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9omjQAAAAASUVORK5CYII="
)


def _normalize_task_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    image_url = result.get("image_url")
    video_url = result.get("video_url")
    direct_url = _first_url(result.get("url"))
    b64_json = result.get("b64_json")
    b64_data = result.get("b64_data")
    revised_prompt = result.get("revised_prompt")
    if image_url or video_url or direct_url or b64_json or b64_data:
        return [
            {
                "url": image_url or video_url or direct_url,
                "b64_json": b64_json,
                "b64_data": b64_data,
                "revised_prompt": revised_prompt,
            }
        ]
    for key in ("image_urls", "video_urls"):
        urls = result.get(key)
        if isinstance(urls, list):
            normalized_from_urls: list[dict[str, Any]] = []
            for row_url in urls:
                final_url = _first_url(row_url)
                if final_url:
                    normalized_from_urls.append({"url": final_url})
            if normalized_from_urls:
                return normalized_from_urls
    images = result.get("images")
    if isinstance(images, list):
        normalized: list[dict[str, Any]] = []
        for item in images:
            if not isinstance(item, dict):
                continue
            row_url = item.get("url")
            final_url = _first_url(row_url)
            normalized.append(
                {
                    "url": final_url,
                    "b64_json": item.get("b64_json"),
                    "b64_data": item.get("b64_data"),
                    "revised_prompt": item.get("revised_prompt"),
                }
            )
        if normalized:
            return normalized
    videos = result.get("videos")
    if isinstance(videos, list):
        normalized_videos: list[dict[str, Any]] = []
        for item in videos:
            if not isinstance(item, dict):
                continue
            final_url = _first_url(item.get("url")) or _first_url(item.get("video_url")) or _first_url(item.get("video_urls"))
            normalized_videos.append(
                {
                    "url": final_url,
                    "b64_json": item.get("b64_json"),
                    "b64_data": item.get("b64_data"),
                }
            )
        if normalized_videos:
            return normalized_videos
    data = result.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


def _first_url(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, str):
            return first
    return None


@dataclass(slots=True)
class LlmResponse:
    text: str
    model_used: str
    tokens_prompt: int = 0
    tokens_completion: int = 0
    estimated_cost: float = 0.0


@dataclass(slots=True)
class MultimodalChatRequest:
    prompt: str
    model: str
    image_urls: list[str] = field(default_factory=list)
    video_urls: list[str] = field(default_factory=list)


@dataclass(slots=True)
class GeneratedImage:
    url: str | None = None
    b64_json: str | None = None
    revised_prompt: str | None = None
    mime_type: str = "image/png"


@dataclass(slots=True)
class ImageGenRequest:
    model: str
    prompt: str
    n: int = 1
    size: str = "1:1"


@dataclass(slots=True)
class ImageGenResult:
    model_used: str
    images: list[GeneratedImage] = field(default_factory=list)
    estimated_cost: float = 0.0


@dataclass(slots=True)
class GeneratedVideo:
    url: str | None = None
    b64_data: str | None = None
    mime_type: str = "video/mp4"
    task_id: str | None = None
    status: str | None = None
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class VideoGenRequest:
    model: str
    prompt: str
    duration_seconds: int = 8
    size: str = "9:16"
    resolution: str = "720p"
    n: int = 1


@dataclass(slots=True)
class VideoGenResult:
    model_used: str
    videos: list[GeneratedVideo] = field(default_factory=list)
    estimated_cost: float = 0.0
    task_id: str | None = None
    status: str | None = None
    raw_response: dict[str, Any] = field(default_factory=dict)


class LlmProvider:
    def chat_complete(
        self,
        request: MultimodalChatRequest,
        *,
        api_base_url: str | None = None,
        api_key: str | None = None,
        extra: dict | None = None,
    ) -> LlmResponse:
        raise NotImplementedError

    def generate_image(
        self,
        request: ImageGenRequest,
        *,
        api_base_url: str | None = None,
        api_key: str | None = None,
        extra: dict | None = None,
    ) -> ImageGenResult:
        raise NotImplementedError

    def generate_video(
        self,
        request: VideoGenRequest,
        *,
        api_base_url: str | None = None,
        api_key: str | None = None,
        extra: dict | None = None,
    ) -> VideoGenResult:
        raise NotImplementedError

    def poll_video_task(
        self,
        *,
        task_id: str,
        model: str,
        api_base_url: str | None = None,
        api_key: str | None = None,
        extra: dict | None = None,
    ) -> VideoGenResult:
        raise NotImplementedError

    def complete(
        self,
        prompt: str,
        *,
        model: str,
        api_base_url: str | None = None,
        api_key: str | None = None,
        extra: dict | None = None,
    ) -> LlmResponse:
        return self.chat_complete(
            MultimodalChatRequest(prompt=prompt, model=model),
            api_base_url=api_base_url,
            api_key=api_key,
            extra=extra,
        )


class StubProvider(LlmProvider):
    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name

    def chat_complete(
        self,
        request: MultimodalChatRequest,
        *,
        api_base_url: str | None = None,
        api_key: str | None = None,
        extra: dict | None = None,
    ) -> LlmResponse:
        snippet = request.prompt.strip().replace("\n", " ")[:280]
        text = f"[{self.provider_name}:{request.model}] {snippet}"
        return LlmResponse(
            text=text,
            model_used=request.model,
            tokens_prompt=max(1, len(request.prompt) // 4),
            tokens_completion=max(1, len(text) // 4),
            estimated_cost=0.0,
        )

    def generate_image(
        self,
        request: ImageGenRequest,
        *,
        api_base_url: str | None = None,
        api_key: str | None = None,
        extra: dict | None = None,
    ) -> ImageGenResult:
        return ImageGenResult(
            model_used=request.model,
            images=[GeneratedImage(b64_json=_PLACEHOLDER_PNG_B64, revised_prompt=request.prompt)],
            estimated_cost=0.0,
        )

    def generate_video(
        self,
        request: VideoGenRequest,
        *,
        api_base_url: str | None = None,
        api_key: str | None = None,
        extra: dict | None = None,
    ) -> VideoGenResult:
        return VideoGenResult(model_used=request.model, videos=[GeneratedVideo()], estimated_cost=0.0)

    def poll_video_task(
        self,
        *,
        task_id: str,
        model: str,
        api_base_url: str | None = None,
        api_key: str | None = None,
        extra: dict | None = None,
    ) -> VideoGenResult:
        return VideoGenResult(
            model_used=model,
            videos=[GeneratedVideo(task_id=task_id, status="unknown")],
            task_id=task_id,
            status="unknown",
        )


class OpenAICompatibleProvider(LlmProvider):
    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name
        self._stub = StubProvider(provider_name)

    def _endpoint_candidates(self, base_url: str | None, path: str) -> list[str]:
        if not base_url:
            return []
        normalized = "/" + path.strip("/")
        base = base_url.rstrip("/")
        candidates: list[str] = []
        if base.endswith(normalized):
            candidates.append(base)
        else:
            candidates.append(f"{base}{normalized}")
            if "/v1" not in base:
                candidates.append(f"{base}/v1{normalized}")
        deduped: list[str] = []
        for item in candidates:
            if item not in deduped:
                deduped.append(item)
        return deduped

    def _headers(self, api_key: str | None) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _task_status_candidates(self, base_url: str | None, task_id: str) -> list[str]:
        if not base_url:
            return []
        base = base_url.rstrip("/")
        roots: list[str] = []
        if "/images/generations" in base:
            roots.append(base.split("/images/generations")[0])
        if "/videos/generations" in base:
            roots.append(base.split("/videos/generations")[0])
        roots.append(base)
        roots.append(base.split("/v1")[0] if "/v1" in base else base)
        candidates: list[str] = []
        for root in roots:
            if not root:
                continue
            root = root.rstrip("/")
            if root.endswith("/tasks"):
                candidates.append(f"{root}/{task_id}?language=en")
            else:
                candidates.append(f"{root}/tasks/{task_id}?language=en")
                if not root.endswith("/v1"):
                    candidates.append(f"{root}/v1/tasks/{task_id}?language=en")
        deduped: list[str] = []
        for item in candidates:
            if item not in deduped:
                deduped.append(item)
        return deduped

    def _post_json(self, candidates: list[str], payload: dict, headers: dict[str, str]) -> dict[str, Any]:
        last_error: Exception | None = None
        with httpx.Client(timeout=90.0) as client:
            for idx, url in enumerate(candidates):
                try:
                    response = client.post(url, json=payload, headers=headers)
                except httpx.HTTPError as exc:
                    last_error = exc
                    continue
                if response.status_code in {404, 405} and idx < len(candidates) - 1:
                    last_error = RuntimeError(f"{response.status_code} from {url}")
                    continue
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise RuntimeError(f"invalid response json type from {url}")
                return data
        if last_error:
            raise RuntimeError("request failed for all endpoint candidates") from last_error
        raise RuntimeError("no endpoint candidates")

    def _extract_chat_text(self, payload: dict[str, Any]) -> str:
        choices = payload.get("choices") or []
        if not choices:
            return ""
        message = (choices[0] or {}).get("message", {})
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            chunks: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text" and isinstance(item.get("text"), str):
                        chunks.append(item["text"])
                    elif isinstance(item.get("content"), str):
                        chunks.append(item["content"])
            return "\n".join(chunks).strip()
        return str(content)

    def _extract_task_id(self, payload: dict[str, Any]) -> str | None:
        data = payload.get("data")
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict):
                task_id = first.get("task_id")
                if isinstance(task_id, str) and task_id:
                    return task_id
        if isinstance(data, dict):
            task_id = data.get("task_id")
            if isinstance(task_id, str) and task_id:
                return task_id
        return None

    def _extract_task_status(self, payload: dict[str, Any]) -> str | None:
        data = payload.get("data")
        if isinstance(data, dict):
            status = data.get("status")
            if isinstance(status, str) and status:
                return status.lower()
        status = payload.get("status")
        if isinstance(status, str) and status:
            return status.lower()
        return None

    def _poll_task_result(
        self,
        *,
        base_url: str | None,
        task_id: str,
        headers: dict[str, str],
        max_wait_seconds: int = 240,
        first_poll_delay_seconds: float = 12.0,
        poll_seconds: float = 4.0,
    ) -> dict[str, Any]:
        candidates = self._task_status_candidates(base_url, task_id)
        if not candidates:
            return {}
        if first_poll_delay_seconds > 0:
            time.sleep(first_poll_delay_seconds)
        deadline = time.time() + max_wait_seconds
        last_payload: dict[str, Any] = {}
        while True:
            with httpx.Client(timeout=45.0) as client:
                for idx, url in enumerate(candidates):
                    try:
                        response = client.get(url, headers=headers)
                    except httpx.HTTPError:
                        continue
                    if response.status_code in {404, 405} and idx < len(candidates) - 1:
                        continue
                    response.raise_for_status()
                    try:
                        payload = response.json()
                    except Exception:
                        continue
                    if not isinstance(payload, dict):
                        continue
                    last_payload = payload
                    data = payload.get("data") or {}
                    if not isinstance(data, dict):
                        continue
                    status = str(data.get("status") or "").lower()
                    if status in {"completed", "succeeded", "success"}:
                        result = data.get("result")
                        if isinstance(result, dict):
                            return {"data": _normalize_task_result(result)}
                        return payload
                    if status in {"failed", "cancelled", "canceled"}:
                        return payload
                    if status in {"pending", "processing", "running", "submitted", "queued"}:
                        break
            if time.time() >= deadline:
                return last_payload
            time.sleep(poll_seconds)

    def chat_complete(
        self,
        request: MultimodalChatRequest,
        *,
        api_base_url: str | None = None,
        api_key: str | None = None,
        extra: dict | None = None,
    ) -> LlmResponse:
        if not api_base_url or not api_key:
            return self._stub.chat_complete(request, api_base_url=api_base_url, api_key=api_key, extra=extra)

        messages: list[dict[str, Any]]
        if request.image_urls or request.video_urls:
            content: list[dict[str, Any]] = [{"type": "text", "text": request.prompt}]
            for image_url in request.image_urls:
                content.append({"type": "image_url", "image_url": {"url": image_url}})
            for video_url in request.video_urls:
                content.append({"type": "video_url", "video_url": {"url": video_url}})
            messages = [{"role": "user", "content": content}]
        else:
            messages = [{"role": "user", "content": request.prompt}]

        payload = {"model": request.model, "messages": messages}
        if isinstance(extra, dict) and isinstance(extra.get("chat_payload"), dict):
            payload = {**payload, **extra["chat_payload"]}

        data = self._post_json(
            self._endpoint_candidates(api_base_url, "/chat/completions"),
            payload=payload,
            headers=self._headers(api_key),
        )
        usage = data.get("usage") or {}
        return LlmResponse(
            text=self._extract_chat_text(data),
            model_used=str(data.get("model") or request.model),
            tokens_prompt=int(usage.get("prompt_tokens") or 0),
            tokens_completion=int(usage.get("completion_tokens") or 0),
            estimated_cost=0.0,
        )

    def generate_image(
        self,
        request: ImageGenRequest,
        *,
        api_base_url: str | None = None,
        api_key: str | None = None,
        extra: dict | None = None,
    ) -> ImageGenResult:
        if not api_base_url or not api_key:
            return self._stub.generate_image(request, api_base_url=api_base_url, api_key=api_key, extra=extra)

        payload: dict[str, Any] = {
            "model": request.model,
            "prompt": request.prompt,
            "n": request.n,
            "size": request.size,
        }
        if isinstance(extra, dict) and isinstance(extra.get("image_payload"), dict):
            payload = {**payload, **extra["image_payload"]}

        data = self._post_json(
            self._endpoint_candidates(api_base_url, "/images/generations"),
            payload=payload,
            headers=self._headers(api_key),
        )
        task_id = self._extract_task_id(data)
        if task_id:
            polled = self._poll_task_result(base_url=api_base_url, task_id=task_id, headers=self._headers(api_key))
            if isinstance(polled, dict) and polled:
                task_data = polled.get("data")
                if isinstance(task_data, dict):
                    status = str(task_data.get("status") or "").lower()
                    if status and status not in {"completed", "succeeded", "success"}:
                        raise RuntimeError(f"image task not completed: status={status}")
                data = polled
        rows = data.get("data") or []
        if not isinstance(rows, list):
            rows = []
        images: list[GeneratedImage] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            images.append(
                GeneratedImage(
                    url=_first_url(row.get("url")),
                    b64_json=row.get("b64_json"),
                    revised_prompt=row.get("revised_prompt"),
                    mime_type=row.get("mime_type") or "image/png",
                )
            )
        if not images:
            images.append(GeneratedImage(b64_json=_PLACEHOLDER_PNG_B64, revised_prompt=request.prompt))
        return ImageGenResult(
            model_used=str(data.get("model") or request.model),
            images=images,
            estimated_cost=0.0,
        )

    def generate_video(
        self,
        request: VideoGenRequest,
        *,
        api_base_url: str | None = None,
        api_key: str | None = None,
        extra: dict | None = None,
    ) -> VideoGenResult:
        if not api_base_url or not api_key:
            return self._stub.generate_video(request, api_base_url=api_base_url, api_key=api_key, extra=extra)

        model_name = request.model
        if model_name == "douban-seedance-2-0":
            # Backward-compatible alias used in older configs.
            model_name = "doubao-seedance-2.0"

        payload: dict[str, Any] = {
            "model": model_name,
            "prompt": request.prompt,
            "n": request.n,
            "size": request.size,
            "resolution": request.resolution,
            "duration": request.duration_seconds,
        }
        if isinstance(extra, dict) and isinstance(extra.get("video_payload"), dict):
            payload = {**payload, **extra["video_payload"]}

        data = self._post_json(
            self._endpoint_candidates(api_base_url, "/videos/generations"),
            payload=payload,
            headers=self._headers(api_key),
        )
        task_id = self._extract_task_id(data)
        status = self._extract_task_status(data)
        if task_id:
            max_wait_seconds = int((extra or {}).get("poll_max_wait_seconds") or (extra or {}).get("video_poll_max_wait_seconds") or 45)
            if not (extra or {}).get("submit_only"):
                polled = self._poll_task_result(
                    base_url=api_base_url,
                    task_id=task_id,
                    headers=self._headers(api_key),
                    max_wait_seconds=max_wait_seconds,
                )
                if isinstance(polled, dict) and polled:
                    status = self._extract_task_status(polled) or status
                    task_data = polled.get("data")
                    if isinstance(task_data, dict):
                        status = str(task_data.get("status") or "").lower() or status
                    data = polled

        rows = data.get("data") or []
        if not isinstance(rows, list):
            rows = []
        videos: list[GeneratedVideo] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            videos.append(
                GeneratedVideo(
                    url=_first_url(row.get("url")) or _first_url(row.get("video_url")) or _first_url(row.get("video_urls")),
                    b64_data=row.get("b64_data") or row.get("b64_json"),
                    mime_type=row.get("mime_type") or "video/mp4",
                    task_id=task_id or row.get("task_id"),
                    status=status,
                    raw_response=row,
                )
            )
        if not videos:
            videos.append(GeneratedVideo(task_id=task_id, status=status, raw_response=data))
        return VideoGenResult(
            model_used=str(data.get("model") or model_name),
            videos=videos,
            estimated_cost=0.0,
            task_id=task_id,
            status=status,
            raw_response=data,
        )

    def poll_video_task(
        self,
        *,
        task_id: str,
        model: str,
        api_base_url: str | None = None,
        api_key: str | None = None,
        extra: dict | None = None,
    ) -> VideoGenResult:
        if not api_base_url or not api_key:
            return self._stub.poll_video_task(task_id=task_id, model=model, api_base_url=api_base_url, api_key=api_key, extra=extra)
        model_name = "doubao-seedance-2.0" if model == "douban-seedance-2-0" else model
        data = self._poll_task_result(
            base_url=api_base_url,
            task_id=task_id,
            headers=self._headers(api_key),
            max_wait_seconds=0,
            first_poll_delay_seconds=0,
        )
        status = self._extract_task_status(data)
        rows = data.get("data") or []
        if not isinstance(rows, list):
            rows = []
        videos: list[GeneratedVideo] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            videos.append(
                GeneratedVideo(
                    url=_first_url(row.get("url")) or _first_url(row.get("video_url")) or _first_url(row.get("video_urls")),
                    b64_data=row.get("b64_data") or row.get("b64_json"),
                    mime_type=row.get("mime_type") or "video/mp4",
                    task_id=task_id,
                    status=status,
                    raw_response=row,
                )
            )
        if not videos:
            videos.append(GeneratedVideo(task_id=task_id, status=status, raw_response=data))
        return VideoGenResult(
            model_used=str(data.get("model") or model_name),
            videos=videos,
            task_id=task_id,
            status=status,
            raw_response=data,
        )


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, LlmProvider] = {
            "openai": OpenAICompatibleProvider("openai"),
            "kimi": OpenAICompatibleProvider("kimi"),
            "xai": OpenAICompatibleProvider("xai"),
            "apimart": OpenAICompatibleProvider("apimart"),
            "stub": StubProvider("stub"),
        }

    def get(self, name: str) -> LlmProvider:
        if name in self._providers:
            return self._providers[name]
        self._providers[name] = OpenAICompatibleProvider(name)
        return self._providers[name]


def decode_placeholder_png() -> bytes:
    return base64.b64decode(_PLACEHOLDER_PNG_B64)

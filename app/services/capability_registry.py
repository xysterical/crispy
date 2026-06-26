from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _norm(value: str | None) -> str:
    return (value or "").strip().lower()


def _contains_any(value: str, hints: tuple[str, ...]) -> bool:
    return any(hint in value for hint in hints)


@dataclass(frozen=True, slots=True)
class CapabilitySpec:
    key: str
    capability: str
    stage_name: str
    agent_name: str
    provider_name: str | None
    model_name: str | None
    api_base_url: str | None = None
    api_key_env: str | None = None
    api_key_available: bool = False
    supported: bool | None = None
    supports: dict[str, bool | None] = field(default_factory=dict)
    setup_hint: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def assess_capability(
    capability: str,
    *,
    provider: str | None,
    model: str | None,
    api_base_url: str | None = None,
    extra: dict | None = None,
) -> bool | None:
    p = _norm(provider)
    m = _norm(model)
    b = _norm(api_base_url)
    if not m and not p:
        return None

    if capability == "image_understanding":
        if "deepseek" in m and not _contains_any(m, ("vl", "vision", "janus")):
            return False
        if _contains_any(m, ("kimi-k2.6", "kimi-k2.5", "gpt-4o", "gpt-4.1", "gpt-5", "gemini", "claude", "vision", "vl", "janus")):
            return True
        if p in {"kimi", "openai", "xai"}:
            return None
        return None

    if capability == "video_understanding":
        if "deepseek" in m and not _contains_any(m, ("vl", "vision", "janus")):
            return False
        if _contains_any(m, ("kimi-k2.6", "kimi-k2.5", "gemini", "qwen-vl", "video-understand")):
            return True
        if p == "kimi":
            return True
        if p in {"openai", "xai"}:
            return None
        return None

    if capability == "image_generation":
        if "/images/" in b:
            return True
        if _contains_any(m, ("gpt-image", "flux", "sdxl", "stable-diffusion", "recraft", "imagen", "dall")):
            return True
        if _contains_any(m, ("deepseek", "kimi-k2", "gpt-4.1", "gpt-5", "claude")):
            return False
        if p in {"openai", "apimart"}:
            return None
        return None

    if capability == "reference_image_edit":
        image_extra = ((extra or {}).get("image_config") or {}) if isinstance(extra, dict) else {}
        for key in ("supports_reference_edit", "reference_edit_supported", "supports_image_references"):
            if key in image_extra:
                return bool(image_extra.get(key))
        if "/images/" in b and _contains_any(m, ("gpt-image", "flux-kontext", "qwen-image-edit", "seedream", "recraft")):
            return True
        if _contains_any(m, ("gpt-image", "flux-kontext", "qwen-image-edit", "image-edit", "seedream", "recraft")):
            return True
        if _contains_any(m, ("dall", "sdxl", "stable-diffusion")):
            return None
        if p in {"openai", "apimart", "xai", "kimi"}:
            return None
        return None

    if capability == "video_generation":
        if "/videos/" in b:
            return True
        if _contains_any(m, ("seedance", "doubao-seedance", "sora", "veo", "kling", "hunyuan-video", "runway", "pika", "vidu")):
            return True
        if _contains_any(m, ("deepseek", "kimi-k2", "gpt-4.1", "gpt-5", "claude", "gemini")):
            return False
        if p in {"openai", "apimart"}:
            return None
        return None

    return None


def capability_spec(
    *,
    key: str,
    capability: str,
    stage_name: str,
    agent_name: str,
    cfg: dict[str, Any],
) -> CapabilitySpec:
    if capability in {"image_generation", "reference_image_edit"}:
        provider = cfg.get("image_provider_name")
        model = cfg.get("image_model_name")
        api_base_url = cfg.get("image_api_base_url")
        api_key_env = cfg.get("image_api_key_env")
        api_key_available = bool(cfg.get("image_api_key_available"))
    elif capability == "video_generation":
        provider = cfg.get("video_provider_name")
        model = cfg.get("video_model_name")
        api_base_url = cfg.get("video_api_base_url")
        api_key_env = cfg.get("video_api_key_env")
        api_key_available = bool(cfg.get("video_api_key_available"))
    else:
        provider = cfg.get("provider_name")
        model = cfg.get("model_name")
        api_base_url = cfg.get("api_base_url")
        api_key_env = cfg.get("api_key_env")
        api_key_available = bool(cfg.get("api_key_available"))

    supported = assess_capability(
        capability,
        provider=provider,
        model=model,
        api_base_url=api_base_url,
        extra=cfg.get("extra"),
    )
    return CapabilitySpec(
        key=key,
        capability=capability,
        stage_name=stage_name,
        agent_name=agent_name,
        provider_name=provider,
        model_name=model,
        api_base_url=api_base_url,
        api_key_env=api_key_env,
        api_key_available=api_key_available,
        supported=supported,
        supports={capability: supported},
        setup_hint="" if supported is not False else "Switch to a model/provider that supports this capability.",
    )

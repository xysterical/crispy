from __future__ import annotations

import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.models import AgentApiConfig


DEFAULT_AGENT_NAME = "default"
API_KEY_ENV_PREFIX = "CRISPY_API_KEY_"


def _default_values() -> dict:
    return {
        "provider_name": "openai",
        "model_name": "gpt-4.1",
        "api_base_url": None,
        "api_key_env": None,
        "extra": {},
    }


def _validate_env_name(env_name: str | None) -> None:
    if env_name and not env_name.startswith(API_KEY_ENV_PREFIX):
        raise ValueError(f"api_key_env must start with {API_KEY_ENV_PREFIX}")


def _modality_config_from_extra(extra: dict | None, key: str) -> dict[str, Any]:
    if not isinstance(extra, dict):
        return {}
    row = extra.get(key)
    if not isinstance(row, dict):
        return {}
    return dict(row)


def _merge_modality_config(
    current_cfg: dict[str, Any],
    *,
    provider_name: str | None,
    model_name: str | None,
    api_base_url: str | None,
    api_key_env: str | None,
) -> dict[str, Any]:
    merged = dict(current_cfg)
    if provider_name is not None:
        value = provider_name.strip()
        if value:
            merged["provider_name"] = value
        else:
            merged.pop("provider_name", None)
    if model_name is not None:
        value = model_name.strip()
        if value:
            merged["model_name"] = value
        else:
            merged.pop("model_name", None)
    if api_base_url is not None:
        value = api_base_url.strip()
        if value:
            merged["api_base_url"] = value
        else:
            merged.pop("api_base_url", None)
    if api_key_env is not None:
        value = api_key_env.strip()
        if value:
            merged["api_key_env"] = value
        else:
            merged.pop("api_key_env", None)
    return merged


def ensure_default_agent_config(db: Session) -> AgentApiConfig:
    row = db.scalar(select(AgentApiConfig).where(AgentApiConfig.agent_name == DEFAULT_AGENT_NAME))
    if row:
        return row
    row = AgentApiConfig(agent_name=DEFAULT_AGENT_NAME, **_default_values())
    db.add(row)
    db.flush()
    return row


def list_agent_configs(db: Session) -> list[AgentApiConfig]:
    ensure_default_agent_config(db)
    rows = db.scalars(select(AgentApiConfig).order_by(AgentApiConfig.agent_name.asc())).all()
    return rows


def upsert_agent_config(
    db: Session,
    *,
    agent_name: str,
    provider_name: str | None,
    model_name: str | None,
    api_base_url: str | None,
    api_key_env: str | None,
    image_provider_name: str | None = None,
    image_model_name: str | None = None,
    image_api_base_url: str | None = None,
    image_api_key_env: str | None = None,
    video_provider_name: str | None = None,
    video_model_name: str | None = None,
    video_api_base_url: str | None = None,
    video_api_key_env: str | None = None,
    extra: dict | None,
) -> AgentApiConfig:
    _validate_env_name(api_key_env)
    _validate_env_name(image_api_key_env)
    _validate_env_name(video_api_key_env)
    ensure_default_agent_config(db)
    row = db.scalar(select(AgentApiConfig).where(AgentApiConfig.agent_name == agent_name))
    has_image_patch = any(
        value is not None
        for value in (image_provider_name, image_model_name, image_api_base_url, image_api_key_env)
    )
    has_video_patch = any(
        value is not None
        for value in (video_provider_name, video_model_name, video_api_base_url, video_api_key_env)
    )

    if not row:
        defaults = _default_values()
        extra_payload = dict(extra) if isinstance(extra, dict) else dict(defaults["extra"])
        merged_image = _merge_modality_config(
            _modality_config_from_extra(extra_payload, "image_config"),
            provider_name=image_provider_name,
            model_name=image_model_name,
            api_base_url=image_api_base_url,
            api_key_env=image_api_key_env,
        )
        if merged_image:
            extra_payload["image_config"] = merged_image
        merged_video = _merge_modality_config(
            _modality_config_from_extra(extra_payload, "video_config"),
            provider_name=video_provider_name,
            model_name=video_model_name,
            api_base_url=video_api_base_url,
            api_key_env=video_api_key_env,
        )
        if merged_video:
            extra_payload["video_config"] = merged_video
        row = AgentApiConfig(
            agent_name=agent_name,
            provider_name=provider_name or defaults["provider_name"],
            model_name=model_name or defaults["model_name"],
            api_base_url=api_base_url if api_base_url is not None else defaults["api_base_url"],
            api_key_env=api_key_env if api_key_env is not None else defaults["api_key_env"],
            extra=extra_payload,
        )
        db.add(row)
        db.flush()
        return row

    if provider_name is not None:
        row.provider_name = provider_name
    if model_name is not None:
        row.model_name = model_name
    if api_base_url is not None:
        row.api_base_url = api_base_url or None
    if api_key_env is not None:
        row.api_key_env = api_key_env or None

    base_extra = dict(extra) if isinstance(extra, dict) else dict(row.extra or {})
    if has_image_patch:
        merged_image = _merge_modality_config(
            _modality_config_from_extra(base_extra, "image_config"),
            provider_name=image_provider_name,
            model_name=image_model_name,
            api_base_url=image_api_base_url,
            api_key_env=image_api_key_env,
        )
        if merged_image:
            base_extra["image_config"] = merged_image
        else:
            base_extra.pop("image_config", None)
    if has_video_patch:
        merged_video = _merge_modality_config(
            _modality_config_from_extra(base_extra, "video_config"),
            provider_name=video_provider_name,
            model_name=video_model_name,
            api_base_url=video_api_base_url,
            api_key_env=video_api_key_env,
        )
        if merged_video:
            base_extra["video_config"] = merged_video
        else:
            base_extra.pop("video_config", None)
    if extra is not None or has_image_patch or has_video_patch:
        row.extra = base_extra

    db.flush()
    return row


def _resolved_image_config(default_cfg: AgentApiConfig, agent_cfg: AgentApiConfig | None, text_fallback: dict) -> dict:
    default_image = _modality_config_from_extra(default_cfg.extra, "image_config")
    agent_image = _modality_config_from_extra(agent_cfg.extra if agent_cfg else None, "image_config")
    image_provider_name = (
        agent_image.get("provider_name")
        or default_image.get("provider_name")
        or text_fallback["provider_name"]
    )
    image_model_name = (
        agent_image.get("model_name")
        or default_image.get("model_name")
        or "gpt-image-2"
    )
    image_api_base_url = (
        agent_image.get("api_base_url")
        or default_image.get("api_base_url")
        or text_fallback["api_base_url"]
    )
    image_api_key_env = (
        agent_image.get("api_key_env")
        or default_image.get("api_key_env")
        or text_fallback["api_key_env"]
    )
    return {
        "provider_name": image_provider_name,
        "model_name": image_model_name,
        "api_base_url": image_api_base_url,
        "api_key_env": image_api_key_env,
        "api_key_available": bool(os.getenv(image_api_key_env)) if image_api_key_env else False,
    }


def _resolved_video_config(default_cfg: AgentApiConfig, agent_cfg: AgentApiConfig | None, text_fallback: dict) -> dict:
    default_video = _modality_config_from_extra(default_cfg.extra, "video_config")
    agent_video = _modality_config_from_extra(agent_cfg.extra if agent_cfg else None, "video_config")
    video_provider_name = (
        agent_video.get("provider_name")
        or default_video.get("provider_name")
        or text_fallback["provider_name"]
    )
    video_model_name = (
        agent_video.get("model_name")
        or default_video.get("model_name")
        or "doubao-seedance-2.0"
    )
    video_api_base_url = (
        agent_video.get("api_base_url")
        or default_video.get("api_base_url")
        or text_fallback["api_base_url"]
    )
    video_api_key_env = (
        agent_video.get("api_key_env")
        or default_video.get("api_key_env")
        or text_fallback["api_key_env"]
    )
    return {
        "provider_name": video_provider_name,
        "model_name": video_model_name,
        "api_base_url": video_api_base_url,
        "api_key_env": video_api_key_env,
        "api_key_available": bool(os.getenv(video_api_key_env)) if video_api_key_env else False,
    }


def resolve_agent_config(
    db: Session,
    *,
    agent_name: str,
    run_provider: str,
    run_model: str,
) -> dict:
    default_cfg = ensure_default_agent_config(db)
    agent_cfg = db.scalar(select(AgentApiConfig).where(AgentApiConfig.agent_name == agent_name))
    provider_name = (
        (agent_cfg.provider_name if agent_cfg and agent_cfg.provider_name else None)
        or default_cfg.provider_name
        or run_provider
    )
    model_name = (
        (agent_cfg.model_name if agent_cfg and agent_cfg.model_name else None)
        or default_cfg.model_name
        or run_model
    )
    api_key_env = (agent_cfg.api_key_env if agent_cfg and agent_cfg.api_key_env else default_cfg.api_key_env)
    api_key_available = bool(os.getenv(api_key_env)) if api_key_env else False
    api_base_url = agent_cfg.api_base_url if agent_cfg and agent_cfg.api_base_url else default_cfg.api_base_url
    text_fallback = {
        "provider_name": provider_name,
        "model_name": model_name,
        "api_base_url": api_base_url,
        "api_key_env": api_key_env,
    }
    image = _resolved_image_config(default_cfg, agent_cfg, text_fallback)
    video = _resolved_video_config(default_cfg, agent_cfg, text_fallback)
    return {
        "agent_name": agent_name,
        "provider_name": provider_name,
        "model_name": model_name,
        "api_base_url": api_base_url,
        "api_key_env": api_key_env,
        "api_key_available": api_key_available,
        "extra": (agent_cfg.extra if agent_cfg and agent_cfg.extra else default_cfg.extra),
        "image_provider_name": image["provider_name"],
        "image_model_name": image["model_name"],
        "image_api_base_url": image["api_base_url"],
        "image_api_key_env": image["api_key_env"],
        "image_api_key_available": image["api_key_available"],
        "video_provider_name": video["provider_name"],
        "video_model_name": video["model_name"],
        "video_api_base_url": video["api_base_url"],
        "video_api_key_env": video["api_key_env"],
        "video_api_key_available": video["api_key_available"],
        "source": "agent_override" if agent_cfg else "default",
    }


def resolve_agent_runtime(config: dict) -> dict:
    api_key_env = config.get("api_key_env")
    image_api_key_env = config.get("image_api_key_env")
    video_api_key_env = config.get("video_api_key_env")
    api_key = os.getenv(api_key_env) if api_key_env else None
    image_api_key = os.getenv(image_api_key_env) if image_api_key_env else None
    video_api_key = os.getenv(video_api_key_env) if video_api_key_env else None
    return {
        "api_base_url": config.get("api_base_url"),
        "api_key": api_key,
        "extra": config.get("extra") or {},
        "provider_name": config.get("provider_name"),
        "model_name": config.get("model_name"),
        "image": {
            "provider_name": config.get("image_provider_name"),
            "model_name": config.get("image_model_name"),
            "api_base_url": config.get("image_api_base_url"),
            "api_key": image_api_key,
            "extra": ((config.get("extra") or {}).get("image_config") or {}),
        },
        "video": {
            "provider_name": config.get("video_provider_name"),
            "model_name": config.get("video_model_name"),
            "api_base_url": config.get("video_api_base_url"),
            "api_key": video_api_key,
            "extra": ((config.get("extra") or {}).get("video_config") or {}),
        },
    }


def api_key_available(api_key_env: str | None) -> bool:
    if not api_key_env:
        return False
    return bool(os.getenv(api_key_env))


def list_api_key_env_names(prefix: str = API_KEY_ENV_PREFIX) -> list[str]:
    names = [name for name in os.environ.keys() if name.startswith(prefix)]
    names.sort()
    return names

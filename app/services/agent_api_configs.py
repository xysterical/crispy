from __future__ import annotations

import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.registry import get_agent_spec
from app.data.models import AgentApiConfig


DEFAULT_AGENT_NAME = "default"
API_KEY_ENV_PREFIX = "CRISPY_API_KEY_"


def _default_values() -> dict:
    return {
        "provider_name": "openai",
        "model_name": "gpt-4.1",
        "api_base_url": None,
        "api_key_env": None,
        "thinking_mode": "auto",
        "thinking_budget_tokens": None,
        "max_output_tokens": None,
        "request_timeout_seconds": None,
        "streaming_enabled": False,
        "extra": {},
    }


def _agent_default_values(agent_name: str) -> dict:
    defaults = _default_values()
    if agent_name == "visual_qa_agent":
        return {
            **defaults,
            "provider_name": "deepseek",
            "model_name": "deepseek-v3.2",
            "api_base_url": "https://api.deepseek.com/v1",
            "api_key_env": "CRISPY_API_KEY_DEEPSEEK",
            "max_output_tokens": 1800,
            "request_timeout_seconds": 90,
        }
    return defaults


def ensure_builtin_agent_config(db: Session, agent_name: str) -> AgentApiConfig | None:
    if agent_name != "visual_qa_agent":
        return None
    row = db.scalar(select(AgentApiConfig).where(AgentApiConfig.agent_name == agent_name))
    if row:
        return row
    # Ensure the agent exists in the persona/registry catalog before creating a built-in row.
    get_agent_spec(agent_name)
    row = AgentApiConfig(agent_name=agent_name, **_agent_default_values(agent_name))
    db.add(row)
    db.flush()
    return row


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


def _field_provided(field_name: str, value: Any, update_fields: set[str] | None) -> bool:
    if update_fields is None:
        return value is not None
    return field_name in update_fields


def _merge_modality_config(
    current_cfg: dict[str, Any],
    *,
    provider_name: str | None,
    model_name: str | None,
    api_base_url: str | None,
    api_key_env: str | None,
    update_fields: set[str] | None = None,
    provider_field: str = "provider_name",
    model_field: str = "model_name",
    api_base_url_field: str = "api_base_url",
    api_key_env_field: str = "api_key_env",
) -> dict[str, Any]:
    merged = dict(current_cfg)
    if _field_provided(provider_field, provider_name, update_fields):
        value = (provider_name or "").strip()
        if value:
            merged["provider_name"] = value
        else:
            merged.pop("provider_name", None)
    if _field_provided(model_field, model_name, update_fields):
        value = (model_name or "").strip()
        if value:
            merged["model_name"] = value
        else:
            merged.pop("model_name", None)
    if _field_provided(api_base_url_field, api_base_url, update_fields):
        value = (api_base_url or "").strip()
        if value:
            merged["api_base_url"] = value
        else:
            merged.pop("api_base_url", None)
    if _field_provided(api_key_env_field, api_key_env, update_fields):
        value = (api_key_env or "").strip()
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
    ensure_builtin_agent_config(db, "visual_qa_agent")
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
    thinking_mode: str | None = None,
    thinking_budget_tokens: int | None = None,
    max_output_tokens: int | None = None,
    request_timeout_seconds: int | None = None,
    streaming_enabled: bool | None = None,
    extra: dict | None,
    update_fields: set[str] | None = None,
) -> AgentApiConfig:
    _validate_env_name(api_key_env)
    _validate_env_name(image_api_key_env)
    _validate_env_name(video_api_key_env)
    if thinking_mode is not None and thinking_mode not in {"auto", "enabled", "disabled"}:
        raise ValueError("thinking_mode must be one of: auto, enabled, disabled")
    for field_name, value in {
        "thinking_budget_tokens": thinking_budget_tokens,
        "max_output_tokens": max_output_tokens,
        "request_timeout_seconds": request_timeout_seconds,
    }.items():
        if value is not None and value <= 0:
            raise ValueError(f"{field_name} must be a positive integer")
    ensure_default_agent_config(db)
    row = db.scalar(select(AgentApiConfig).where(AgentApiConfig.agent_name == agent_name))
    has_image_patch = any(
        _field_provided(field_name, value, update_fields)
        for field_name, value in (
            ("image_provider_name", image_provider_name),
            ("image_model_name", image_model_name),
            ("image_api_base_url", image_api_base_url),
            ("image_api_key_env", image_api_key_env),
        )
    )
    has_video_patch = any(
        _field_provided(field_name, value, update_fields)
        for field_name, value in (
            ("video_provider_name", video_provider_name),
            ("video_model_name", video_model_name),
            ("video_api_base_url", video_api_base_url),
            ("video_api_key_env", video_api_key_env),
        )
    )

    if not row:
        defaults = _agent_default_values(agent_name)
        extra_payload = dict(extra) if isinstance(extra, dict) else dict(defaults["extra"])
        merged_image = _merge_modality_config(
            _modality_config_from_extra(extra_payload, "image_config"),
            provider_name=image_provider_name,
            model_name=image_model_name,
            api_base_url=image_api_base_url,
            api_key_env=image_api_key_env,
            update_fields=update_fields,
            provider_field="image_provider_name",
            model_field="image_model_name",
            api_base_url_field="image_api_base_url",
            api_key_env_field="image_api_key_env",
        )
        if merged_image:
            extra_payload["image_config"] = merged_image
        merged_video = _merge_modality_config(
            _modality_config_from_extra(extra_payload, "video_config"),
            provider_name=video_provider_name,
            model_name=video_model_name,
            api_base_url=video_api_base_url,
            api_key_env=video_api_key_env,
            update_fields=update_fields,
            provider_field="video_provider_name",
            model_field="video_model_name",
            api_base_url_field="video_api_base_url",
            api_key_env_field="video_api_key_env",
        )
        if merged_video:
            extra_payload["video_config"] = merged_video
        row = AgentApiConfig(
            agent_name=agent_name,
            provider_name=(provider_name or "").strip(),
            model_name=(model_name or "").strip(),
            api_base_url=(api_base_url or "").strip() or None,
            api_key_env=(api_key_env or "").strip() or None,
            thinking_mode=thinking_mode if thinking_mode is not None else "",
            thinking_budget_tokens=thinking_budget_tokens,
            max_output_tokens=max_output_tokens,
            request_timeout_seconds=request_timeout_seconds,
            streaming_enabled=bool(streaming_enabled) if streaming_enabled is not None else bool(defaults["streaming_enabled"]),
            extra=extra_payload,
        )
        db.add(row)
        db.flush()
        return row

    if _field_provided("provider_name", provider_name, update_fields):
        row.provider_name = (provider_name or "").strip()
    if _field_provided("model_name", model_name, update_fields):
        row.model_name = (model_name or "").strip()
    if _field_provided("api_base_url", api_base_url, update_fields):
        row.api_base_url = (api_base_url or "").strip() or None
    if _field_provided("api_key_env", api_key_env, update_fields):
        row.api_key_env = (api_key_env or "").strip() or None
    if _field_provided("thinking_mode", thinking_mode, update_fields):
        row.thinking_mode = thinking_mode or "auto"
    if _field_provided("thinking_budget_tokens", thinking_budget_tokens, update_fields):
        row.thinking_budget_tokens = thinking_budget_tokens
    if _field_provided("max_output_tokens", max_output_tokens, update_fields):
        row.max_output_tokens = max_output_tokens
    if _field_provided("request_timeout_seconds", request_timeout_seconds, update_fields):
        row.request_timeout_seconds = request_timeout_seconds
    if _field_provided("streaming_enabled", streaming_enabled, update_fields):
        row.streaming_enabled = bool(streaming_enabled)

    base_extra = dict(extra) if isinstance(extra, dict) else dict(row.extra or {})
    if has_image_patch:
        merged_image = _merge_modality_config(
            _modality_config_from_extra(base_extra, "image_config"),
            provider_name=image_provider_name,
            model_name=image_model_name,
            api_base_url=image_api_base_url,
            api_key_env=image_api_key_env,
            update_fields=update_fields,
            provider_field="image_provider_name",
            model_field="image_model_name",
            api_base_url_field="image_api_base_url",
            api_key_env_field="image_api_key_env",
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
            update_fields=update_fields,
            provider_field="video_provider_name",
            model_field="video_model_name",
            api_base_url_field="video_api_base_url",
            api_key_env_field="video_api_key_env",
        )
        if merged_video:
            base_extra["video_config"] = merged_video
        else:
            base_extra.pop("video_config", None)
    if _field_provided("extra", extra, update_fields) or has_image_patch or has_video_patch:
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
    if not agent_cfg:
        agent_cfg = ensure_builtin_agent_config(db, agent_name)
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
    thinking_mode = (agent_cfg.thinking_mode if agent_cfg and agent_cfg.thinking_mode else default_cfg.thinking_mode) or "auto"
    streaming_enabled = (
        agent_cfg.streaming_enabled
        if agent_cfg and agent_cfg.streaming_enabled is not None
        else default_cfg.streaming_enabled
    )
    supports_thinking = provider_name == "kimi" and model_name.startswith("kimi-k")
    return {
        "agent_name": agent_name,
        "provider_name": provider_name,
        "model_name": model_name,
        "api_base_url": api_base_url,
        "api_key_env": api_key_env,
        "api_key_available": api_key_available,
        "thinking_mode": thinking_mode,
        "thinking_applied": bool(supports_thinking and thinking_mode != "disabled"),
        "thinking_budget_tokens": (
            agent_cfg.thinking_budget_tokens
            if agent_cfg and agent_cfg.thinking_budget_tokens is not None
            else default_cfg.thinking_budget_tokens
        ),
        "max_output_tokens": (
            agent_cfg.max_output_tokens
            if agent_cfg and agent_cfg.max_output_tokens is not None
            else default_cfg.max_output_tokens
        ),
        "request_timeout_seconds": (
            agent_cfg.request_timeout_seconds
            if agent_cfg and agent_cfg.request_timeout_seconds is not None
            else default_cfg.request_timeout_seconds
        ),
        "streaming_enabled": bool(streaming_enabled),
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
        "thinking_mode": config.get("thinking_mode") or "auto",
        "thinking_budget_tokens": config.get("thinking_budget_tokens"),
        "max_output_tokens": config.get("max_output_tokens"),
        "request_timeout_seconds": config.get("request_timeout_seconds"),
        "streaming_enabled": bool(config.get("streaming_enabled")),
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


_BUILTIN_INTEGRATION_CONFIGS = [
    {"platform": "shopify", "config_key": "store_domain", "label": "Store Domain", "env_var": "CRISPY_API_KEY_SHOPIFY_DOMAIN", "is_required": True},
    {"platform": "shopify", "config_key": "access_token", "label": "Access Token", "env_var": "CRISPY_API_KEY_SHOPIFY", "is_required": True},
    {"platform": "meta", "config_key": "access_token", "label": "Access Token", "env_var": "CRISPY_API_KEY_META", "is_required": True},
    {"platform": "meta", "config_key": "ad_account_id", "label": "Ad Account ID", "env_var": "CRISPY_API_KEY_META_ACCOUNT", "is_required": True},
    {"platform": "notion", "config_key": "api_key", "label": "API Key (Internal Integration)", "env_var": "CRISPY_API_KEY_NOTION", "is_required": True},
    {"platform": "notion", "config_key": "database_id", "label": "Content Calendar Database ID", "env_var": "CRISPY_API_KEY_NOTION_DATABASE", "is_required": True},
]


def _seed_integration_configs(db: Session) -> None:
    from app.data.models import IntegrationConfig as IntConfig

    for item in _BUILTIN_INTEGRATION_CONFIGS:
        existing = db.scalar(
            select(IntConfig).where(
                IntConfig.platform == item["platform"],
                IntConfig.config_key == item["config_key"],
            )
        )
        if existing:
            # Repair env_var if it was modified away from the built-in default
            if existing.env_var != item["env_var"]:
                existing.env_var = item["env_var"]
        else:
            db.add(IntConfig(**item))
    db.flush()


def list_integration_configs(db: Session) -> list[dict]:
    from app.data.models import IntegrationConfig as IntConfig

    _seed_integration_configs(db)
    rows = db.scalars(select(IntConfig).order_by(IntConfig.platform, IntConfig.config_key)).all()
    return [
        {
            "id": row.id,
            "platform": row.platform,
            "config_key": row.config_key,
            "label": row.label,
            "env_var": row.env_var,
            "is_required": row.is_required,
            "is_set": bool(os.getenv(row.env_var)),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        for row in rows
    ]


def upsert_integration_config(db: Session, platform: str, config_key: str, env_var: str) -> dict:
    from app.data.models import IntegrationConfig as IntConfig

    row = db.scalar(
        select(IntConfig).where(
            IntConfig.platform == platform,
            IntConfig.config_key == config_key,
        )
    )
    if not row:
        label = " ".join(p.capitalize() for p in config_key.split("_"))
        row = IntConfig(
            platform=platform,
            config_key=config_key,
            label=label,
            env_var=env_var,
        )
        db.add(row)
    else:
        row.env_var = env_var
    db.flush()
    return {
        "id": row.id,
        "platform": row.platform,
        "config_key": row.config_key,
        "label": row.label,
        "env_var": row.env_var,
        "is_required": row.is_required,
        "is_set": bool(os.getenv(row.env_var)),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }

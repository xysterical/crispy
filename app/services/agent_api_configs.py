from __future__ import annotations

import os

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
    extra: dict | None,
) -> AgentApiConfig:
    if api_key_env and not api_key_env.startswith(API_KEY_ENV_PREFIX):
        raise ValueError(f"api_key_env must start with {API_KEY_ENV_PREFIX}")
    ensure_default_agent_config(db)
    row = db.scalar(select(AgentApiConfig).where(AgentApiConfig.agent_name == agent_name))
    if not row:
        defaults = _default_values()
        row = AgentApiConfig(
            agent_name=agent_name,
            provider_name=provider_name or defaults["provider_name"],
            model_name=model_name or defaults["model_name"],
            api_base_url=api_base_url if api_base_url is not None else defaults["api_base_url"],
            api_key_env=api_key_env if api_key_env is not None else defaults["api_key_env"],
            extra=extra if extra is not None else defaults["extra"],
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
    if extra is not None:
        row.extra = extra
    db.flush()
    return row


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
    return {
        "agent_name": agent_name,
        "provider_name": provider_name,
        "model_name": model_name,
        "api_base_url": (agent_cfg.api_base_url if agent_cfg and agent_cfg.api_base_url else default_cfg.api_base_url),
        "api_key_env": api_key_env,
        "api_key_available": api_key_available,
        "extra": (agent_cfg.extra if agent_cfg and agent_cfg.extra else default_cfg.extra),
        "source": "agent_override" if agent_cfg else "default",
    }


def resolve_agent_runtime(config: dict) -> dict:
    api_key_env = config.get("api_key_env")
    api_key = os.getenv(api_key_env) if api_key_env else None
    return {
        "api_base_url": config.get("api_base_url"),
        "api_key": api_key,
        "extra": config.get("extra") or {},
    }


def api_key_available(api_key_env: str | None) -> bool:
    if not api_key_env:
        return False
    return bool(os.getenv(api_key_env))


def list_api_key_env_names(prefix: str = API_KEY_ENV_PREFIX) -> list[str]:
    names = [name for name in os.environ.keys() if name.startswith(prefix)]
    names.sort()
    return names

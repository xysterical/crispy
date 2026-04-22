from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CRISPY_")

    app_name: str = "crispy"
    debug: bool = False
    database_url: str = "sqlite:///./crispy.db"
    polling_interval_seconds: float = 1.0
    personas_dir: Path = Field(default=Path("personas"))
    assets_dir: Path = Field(default=Path("assets"))
    default_locale: str = "en-US"
    default_market: str = "US"
    default_provider: str = "kimi"
    default_model: str = "kimi-default-text"
    enable_worker: bool = True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.personas_dir.mkdir(parents=True, exist_ok=True)
    settings.assets_dir.mkdir(parents=True, exist_ok=True)
    return settings

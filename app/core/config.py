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
    worker_concurrency: int = 3
    video_polling_interval_seconds: float = 30.0
    max_stage_retries: int = 3
    retry_base_delay_seconds: float = 10.0
    retry_backoff_multiplier: float = 3.0
    personas_dir: Path = Field(default=Path("personas"))
    assets_dir: Path = Field(default=Path("assets"))
    default_locale: str = "en-US"
    default_market: str = "US"
    default_provider: str = "openai"
    default_model: str = "gpt-4.1"
    enable_worker: bool = True
    # Shopify read-only integration
    shopify_store_domain: str = ""
    shopify_access_token: str = ""
    # Meta Ads read-only integration
    meta_access_token: str = ""
    meta_ad_account_id: str = ""
    # Notion calendar integration
    notion_api_key: str = ""
    notion_database_id: str = ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.personas_dir.mkdir(parents=True, exist_ok=True)
    settings.assets_dir.mkdir(parents=True, exist_ok=True)
    return settings

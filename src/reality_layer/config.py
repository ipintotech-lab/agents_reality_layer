from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REALITY_", env_file=".env", extra="ignore")

    database_url: str = Field(
        default="postgresql+psycopg://reality:reality@localhost:5432/reality"
    )
    object_storage_root: str = "./data/raw_payloads"
    environment: str = "local"
    log_level: str = "INFO"
    persistence_enabled: bool = False
    shopify_domain: str = ""
    shopify_access_token: str = ""
    easypost_api_key: str = ""

    # Verifier worker: bounded read-after-write polling.
    verifier_initial_interval_seconds: float = 2.0
    verifier_backoff_factor: float = 2.0
    verifier_max_interval_seconds: float = 10.0
    verifier_max_attempts: int = 6
    verifier_timeout_seconds: float = 30.0
    verifier_sweep_interval_seconds: float = 5.0


@lru_cache
def get_settings() -> Settings:
    return Settings()

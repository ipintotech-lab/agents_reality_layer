from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REALITY_", env_file=".env", extra="ignore")

    database_url: str = Field(
        default="postgresql+psycopg://reality:reality@localhost:5432/reality"
    )
    environment: str = "local"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()

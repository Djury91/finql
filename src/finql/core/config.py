from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FINQL_", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    # SQLAlchemy URL, e.g. postgresql+asyncpg://user:pass@localhost:5432/finql
    database_url: SecretStr


@lru_cache
def get_settings() -> Settings:
    return Settings()  # database_url comes from the environment

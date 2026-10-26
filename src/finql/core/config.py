from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FINQL_", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    # SQLAlchemy URL, e.g. postgresql+asyncpg://finql_app:pass@localhost:5432/finql
    database_url: SecretStr
    # LLM-generated SQL runs with this one (finql_llm_reader). Used from phase 3.
    llm_database_url: SecretStr | None = None
    # Alembic and the seed (finql_migrator), e.g. postgresql+psycopg://finql_migrator:...
    migration_database_url: SecretStr | None = None
    # Only for `finql db bootstrap`: a superuser or CREATEROLE connection.
    admin_database_url: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()  # database_url comes from the environment

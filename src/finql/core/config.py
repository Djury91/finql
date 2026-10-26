from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FINQL_", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    # JSON logs for machines; unset means console format in dev and JSON everywhere else.
    log_json: bool | None = None

    # SQLAlchemy URL, e.g. postgresql+asyncpg://finql_app:pass@localhost:5432/finql
    database_url: SecretStr
    # LLM-generated SQL runs with this one (finql_llm_reader). Used from phase 3.
    llm_database_url: SecretStr | None = None
    # Alembic, the seed and the user admin CLI (finql_migrator), e.g. postgresql+psycopg://...
    migration_database_url: SecretStr | None = None
    # Only for `finql db bootstrap`: a superuser or CREATEROLE connection.
    admin_database_url: SecretStr | None = None

    # HS256 signing key, 32+ characters:
    # python -c "import secrets; print(secrets.token_urlsafe(48))"
    jwt_secret: SecretStr = Field(min_length=32)
    jwt_issuer: str = "finql"
    access_token_ttl_minutes: int = Field(default=30, gt=0)
    # Password of the demo users (`finql user demo`); never used in production.
    demo_password: SecretStr | None = None

    @property
    def json_logs(self) -> bool:
        return self.log_json if self.log_json is not None else self.env != "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # the required values come from the environment

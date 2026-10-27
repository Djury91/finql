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

    # --- LLM (text-to-SQL) ---
    # "fake": deterministic answers to the example questions, no API key, no cost (demo, tests).
    llm_provider: Literal["anthropic", "fake"] = "anthropic"
    # Unset: the SDK's own lookup (ANTHROPIC_API_KEY, `ant auth login` profile).
    anthropic_api_key: SecretStr | None = None
    # ADR-004: Sonnet for SQL generation (speed and cost of an interactive request).
    llm_model: str = "claude-sonnet-5-5"
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    llm_max_tokens: int = Field(default=16000, gt=0)
    llm_timeout_seconds: float = Field(default=120, gt=0)
    # On a safety refusal the API retries the request on a fallback model it picks by category.
    # Supported by Sonnet 5.5, Opus 5+ and Fable 5.1; turn it off for older models.
    llm_refusal_fallback: bool = True

    # --- Running LLM-generated SQL (docs/05-text-to-sql-biztonsag.md) ---
    sql_default_limit: int = Field(default=200, gt=0)
    sql_max_limit: int = Field(default=1000, gt=0)
    sql_statement_timeout_ms: int = Field(default=5000, gt=0)
    # EXPLAIN thresholds, calibrated on the `large` scale (docs/05-text-to-sql-biztonsag.md).
    # The row estimate of the largest intermediate result is the main one: legitimate queries
    # stay under ~8 million, joins without a proper condition start at ~70 million. The cost is a
    # backstop only: row-level security inflates it (the loans view: 16 million, 0.5 s).
    sql_max_plan_rows: float = Field(default=50_000_000, gt=0)
    sql_max_cost: float = Field(default=100_000_000, gt=0)
    # Self-repair rounds after an SQL error (the first attempt not counted).
    sql_max_repairs: int = Field(default=2, ge=0)

    # --- Dynamic few-shot: the most similar curated examples go into the prompt ---
    # 0 turns it off. Without an embedder (no Voyage key) it is off as well.
    few_shot_k: int = Field(default=3, ge=0, le=10)
    # "hashing": deterministic, offline, lexical similarity only (tests, demo without a key).
    embedding_provider: Literal["voyage", "hashing"] = "voyage"
    voyage_api_key: SecretStr | None = None
    # 1024 dimensions, like the vector(1024) columns. A model change means re-embedding
    # (`finql examples sync`): the vectors of two models are not comparable.
    embedding_model: str = "voyage-4"
    embedding_timeout_seconds: float = Field(default=10, gt=0)

    # --- Documents (RAG) ---
    # Sources in the prompt of a document answer. More finds more, but costs input tokens and
    # gives the model more to get wrong.
    rag_top_k: int = Field(default=5, ge=1, le=20)

    # --- Agent (chat) ---
    # Tool calls per user message; after the last one the model must answer from what it has.
    agent_max_tool_calls: int = Field(default=6, ge=1, le=20)
    # One user message, all model turns and tools together.
    agent_timeout_seconds: float = Field(default=120, gt=0)
    # Earlier turns kept word for word. Beyond this the oldest are summarized, and half stays.
    agent_history_turns: int = Field(default=8, ge=2, le=50)
    # ADR-004: the cheap model for the cheap task (conversation summary).
    summary_model: str = "claude-haiku-5-5"

    # --- MCP server (`finql mcp`, ADR-013) ---
    # The FinQL user the server acts as: every tool runs with this user's rights, like the API.
    # The MCP client (e.g. Claude Desktop) passes them in its server configuration.
    mcp_email: str | None = None
    mcp_password: SecretStr | None = None

    @property
    def json_logs(self) -> bool:
        return self.log_json if self.log_json is not None else self.env != "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # the required values come from the environment

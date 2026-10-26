from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from finql import __version__, health
from finql.audit.router import router as audit_router
from finql.auth.router import router as auth_router
from finql.core.config import Settings, get_settings
from finql.core.db import create_engine, create_sessionmaker
from finql.core.errors import install_error_handlers
from finql.core.logging import RequestContextMiddleware, configure_logging
from finql.llm.anthropic_client import AnthropicClient
from finql.llm.client import LLMClient
from finql.text_to_sql.demo import demo_llm_client
from finql.text_to_sql.router import router as text_to_sql_router
from finql.text_to_sql.schema_context import CatalogCache


def build_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_provider == "fake":
        return demo_llm_client()
    return AnthropicClient(settings)


def create_app(settings: Settings | None = None, *, llm_client: LLMClient | None = None) -> FastAPI:
    """`llm_client`: tests pass a scripted fake; otherwise it follows FINQL_LLM_PROVIDER."""
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_logs=settings.json_logs)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Two pools, two database roles: the application (finql_app: the app schema only) and the
        # LLM-generated SQL (finql_llm_reader: read-only, analytics views only).
        app.state.app_engine = create_engine(settings.database_url.get_secret_value())
        app.state.sessionmaker = create_sessionmaker(app.state.app_engine)
        app.state.llm_engine = (
            create_engine(settings.llm_database_url.get_secret_value())
            if settings.llm_database_url
            else None
        )
        app.state.catalog_cache = CatalogCache()
        app.state.llm_client = llm_client or build_llm_client(settings)
        try:
            yield
        finally:
            if isinstance(app.state.llm_client, AnthropicClient):
                await app.state.llm_client.close()
            await app.state.app_engine.dispose()
            if app.state.llm_engine is not None:
                await app.state.llm_engine.dispose()

    app = FastAPI(title="FinQL", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(auth_router)
    app.include_router(text_to_sql_router)
    app.include_router(audit_router)
    return app

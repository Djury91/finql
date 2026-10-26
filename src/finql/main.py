from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from finql import __version__, health
from finql.auth.router import router as auth_router
from finql.core.config import Settings, get_settings
from finql.core.db import create_engine, create_sessionmaker
from finql.core.errors import install_error_handlers
from finql.core.logging import RequestContextMiddleware, configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_logs=settings.json_logs)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Two pools, two database roles: the application (finql_app: the app schema only) and the
        # LLM-generated SQL (finql_llm_reader: read-only, analytics views only, from phase 3).
        app.state.app_engine = create_engine(settings.database_url.get_secret_value())
        app.state.sessionmaker = create_sessionmaker(app.state.app_engine)
        app.state.llm_engine = (
            create_engine(settings.llm_database_url.get_secret_value())
            if settings.llm_database_url
            else None
        )
        try:
            yield
        finally:
            await app.state.app_engine.dispose()
            if app.state.llm_engine is not None:
                await app.state.llm_engine.dispose()

    app = FastAPI(title="FinQL", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(auth_router)
    return app

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from finql import __version__, health
from finql.core.config import Settings, get_settings
from finql.core.db import create_engine


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = create_engine(settings.database_url.get_secret_value())
        try:
            yield
        finally:
            await app.state.engine.dispose()

    app = FastAPI(title="FinQL", version=__version__, lifespan=lifespan)
    app.include_router(health.router)
    return app

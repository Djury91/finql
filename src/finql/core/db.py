from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: response models may still read attributes after the commit.
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One session and one transaction per request: commit on success, rollback on any error."""
    sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with sessionmaker() as session, session.begin():
        yield session


def sync_url(url: str) -> str:
    """The same database with the synchronous psycopg driver (Alembic, seed)."""
    return make_url(url).set(drivername="postgresql+psycopg").render_as_string(hide_password=False)


def async_url(url: str) -> str:
    """The same database with the asyncpg driver (application code, admin CLI)."""
    return make_url(url).set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)


def psycopg_conninfo(url: str) -> str:
    """A SQLAlchemy URL (any PostgreSQL driver) as a libpq URI for `psycopg.connect()`."""
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)

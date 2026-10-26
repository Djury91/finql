from sqlalchemy import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)


def sync_url(url: str) -> str:
    """The same database with the synchronous psycopg driver (Alembic, seed)."""
    return make_url(url).set(drivername="postgresql+psycopg").render_as_string(hide_password=False)


def psycopg_conninfo(url: str) -> str:
    """A SQLAlchemy URL (any PostgreSQL driver) as a libpq URI for `psycopg.connect()`."""
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)

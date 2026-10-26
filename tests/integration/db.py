"""Connection URLs per role and the setup steps a fresh database goes through."""

from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import make_url

from finql.core.bootstrap import bootstrap_database
from finql.core.db import psycopg_conninfo

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class DbUrls:
    """SQLAlchemy URLs (psycopg driver) of one database, per role."""

    admin: str
    migrator: str
    app: str
    llm_reader: str

    def conninfo(self, role: str) -> str:
        url: str = getattr(self, role)
        return psycopg_conninfo(url)

    @classmethod
    def for_database(cls, admin_url: str, database: str | None = None) -> "DbUrls":
        admin = make_url(admin_url).set(drivername="postgresql+psycopg")
        if database is not None:
            admin = admin.set(database=database)

        def as_role(role: str) -> str:
            url = admin.set(username=role, password=f"test-{role}")
            return url.render_as_string(hide_password=False)

        return cls(
            admin=admin.render_as_string(hide_password=False),
            migrator=as_role("finql_migrator"),
            app=as_role("finql_app"),
            llm_reader=as_role("finql_llm_reader"),
        )


def alembic_config(url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    config.attributes["configure_logger"] = False  # keep pytest's logging setup
    return config


def prepare_database(urls: DbUrls) -> None:
    """What a fresh environment goes through: bootstrap, then all migrations."""
    bootstrap_database(urls.admin, [urls.migrator, urls.app, urls.llm_reader])
    command.upgrade(alembic_config(urls.migrator), "head")

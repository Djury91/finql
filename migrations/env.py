from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool, text

from finql.core.config import get_settings
from finql.core.db import sync_url
from finql.models import Base

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

# Every object belongs to finql_owner, whoever runs the migration (finql_migrator or an admin).
OWNER_ROLE = "finql_owner"

# Hand-written SQL (db/) owns these schemas. Autogenerate must not see them, otherwise it
# would offer to drop every table that has no SQLAlchemy model.
DB_FIRST_SCHEMAS = frozenset({"bank", "analytics", "app_ctx"})

target_metadata = Base.metadata


def include_name(name: str | None, type_: str, parent_names: object) -> bool:
    """Reflection side: do not even look at the DB-first schemas in the database."""
    if type_ == "schema":
        return name not in DB_FIRST_SCHEMAS
    return True


def include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    """Model side: skip DB-first tables declared only as foreign key targets (bank.branches)."""
    if type_ == "table":
        return getattr(obj, "schema", None) not in DB_FIRST_SCHEMAS
    return True


def database_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url
    configured = get_settings().migration_database_url
    if configured is None:
        raise RuntimeError("FINQL_MIGRATION_DATABASE_URL nincs beállítva (lásd .env.example)")
    return sync_url(configured.get_secret_value())


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        include_name=include_name,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.execute(f"SET ROLE {OWNER_ROLE}")
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        # Session-level, so it outlives this commit and applies to the version table too.
        connection.execute(text(f"SET ROLE {OWNER_ROLE}"))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_name=include_name,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

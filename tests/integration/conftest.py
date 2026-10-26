import os
import sys
from collections.abc import Iterator

import pytest

# Docker Desktop on Windows exposes the Ryuk reaper port too late, so testcontainers fails at
# startup. The `with` block below stops the container anyway; Ryuk stays enabled on CI (Linux).
if sys.platform == "win32":
    os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

from testcontainers.community.postgres import PostgresContainer

from finql.pipelines.seed.loader import load
from finql.pipelines.seed.scales import SCALES

from .db import DbUrls, prepare_database

POSTGRES_IMAGE = "pgvector/pgvector:pg18"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """Superuser URL (asyncpg) of the test container's database."""
    with PostgresContainer(POSTGRES_IMAGE, driver="asyncpg") as postgres:
        yield postgres.get_connection_url()


@pytest.fixture(scope="session")
def migrated_db(database_url: str) -> DbUrls:
    urls = DbUrls.for_database(database_url)
    prepare_database(urls)
    return urls


@pytest.fixture(scope="session")
def seeded_db(migrated_db: DbUrls) -> DbUrls:
    load(migrated_db.conninfo("migrator"), SCALES["tiny"], seed=42)
    return migrated_db

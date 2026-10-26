import os
import sys
from collections.abc import Iterator

import pytest

# Docker Desktop on Windows exposes the Ryuk reaper port too late, so testcontainers fails at
# startup. The `with` block below stops the container anyway; Ryuk stays enabled on CI (Linux).
if sys.platform == "win32":
    os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

from testcontainers.community.postgres import PostgresContainer

POSTGRES_IMAGE = "pgvector/pgvector:pg18"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with PostgresContainer(POSTGRES_IMAGE, driver="asyncpg") as postgres:
        yield postgres.get_connection_url()

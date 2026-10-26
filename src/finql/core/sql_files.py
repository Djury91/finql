"""Running the hand-written, DB-first SQL files under `db/`."""

from pathlib import Path
from typing import Any

from alembic import context, op

# src/finql/core/sql_files.py → repository root
DB_DIR = Path(__file__).resolve().parents[3] / "db"


def read_sql(relative_path: str) -> str:
    """Return a file from `db/`. The files are reviewed repository content, not user input."""
    return (DB_DIR / relative_path).read_text(encoding="utf-8")


def run_sql_file(relative_path: str) -> None:
    """Execute a whole SQL file inside the current Alembic migration.

    Online, the file goes to the driver as-is (simple query protocol), so multiple statements,
    `DO` blocks and `%` in `format()` need no escaping. Offline (`alembic upgrade --sql`) the
    text is emitted into the generated script for review.
    """
    sql = read_sql(relative_path)
    if context.is_offline_mode():
        op.execute(sql)
        return
    dbapi_connection: Any = op.get_bind().connection.dbapi_connection
    with dbapi_connection.cursor() as cursor:
        cursor.execute(sql)

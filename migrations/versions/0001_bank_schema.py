"""bank schema: types, tables, monthly partitioning, indexes, grants (DB-first)

Revision ID: 0001
Revises:
Create Date: 2026-10-26
"""

from collections.abc import Sequence

from alembic import op

from finql.core.sql_files import run_sql_file

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SQL_FILES = (
    "bank/000_schema.sql",
    "bank/001_types.sql",
    "bank/002_reference.sql",
    "bank/003_customers_accounts.sql",
    "bank/004_loans.sql",
    "bank/010_transactions.sql",
    "bank/020_indexes.sql",
    "bank/090_grants.sql",
)


def upgrade() -> None:
    for path in SQL_FILES:
        run_sql_file(path)


def downgrade() -> None:
    op.execute("DROP SCHEMA bank CASCADE")

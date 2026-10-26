"""row-level security: app_ctx session functions, branch_scope policies (DB-first)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-26
"""

from collections.abc import Sequence

from alembic import op

from finql.core.sql_files import run_sql_file

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_TABLES = ("customers", "accounts", "cards", "loans", "loan_installments", "transactions")


def upgrade() -> None:
    run_sql_file("security/001_app_ctx.sql")
    run_sql_file("security/010_rls.sql")


def downgrade() -> None:
    for table in RLS_TABLES:
        op.execute(f"DROP POLICY branch_scope ON bank.{table}")
        op.execute(f"ALTER TABLE bank.{table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP SCHEMA app_ctx CASCADE")

"""analytics schema: PII-free views for the LLM, monthly summary, comments (DB-first)

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

from finql.core.sql_files import run_sql_file

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SQL_FILES = (
    "analytics/000_schema.sql",
    "analytics/010_reference.sql",
    "analytics/020_customers_accounts.sql",
    "analytics/030_transactions.sql",
    "analytics/040_loans.sql",
    "analytics/050_monthly_account_summary.sql",
    "analytics/090_comments.sql",
    # Last: COMMENT ON needs ownership, and finql_owner does not inherit finql_analytics.
    "analytics/099_ownership_grants.sql",
)


def upgrade() -> None:
    # Handing the views to finql_analytics needs a role membership that only the admin-level
    # bootstrap can grant. Fail with a clear hint instead of a bare "must be able to SET ROLE".
    if not context.is_offline_mode():
        can_set = op.get_bind().scalar(sa.text("SELECT pg_has_role('finql_analytics', 'SET')"))
        if not can_set:
            raise RuntimeError(
                "A finql_owner nem léphet a finql_analytics nevében. "
                "Futtasd újra: uv run finql db bootstrap"
            )
    for path in SQL_FILES:
        run_sql_file(path)


def downgrade() -> None:
    # The schema owner may drop the views even though finql_analytics owns them.
    op.execute("DROP SCHEMA analytics CASCADE")
    op.execute("DROP MATERIALIZED VIEW bank.monthly_account_summary")

"""hash-chained logs: query_log and answer_log (columns code-first, the chain DB-first)

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from finql.core.sql_files import run_sql_file

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LOGS = ("query_log", "answer_log")
COMMENTS = {
    "chain_seq": "Sorszám a hash-láncban: hézag nélkül 1-től (trigger tölti).",
    "prev_hash": "Az előző sor row_hash-e; az első soré 32 nulla bájt.",
    "row_hash": "SHA-256 a sor tartalmára és a prev_hash-re (app.log_row_hash).",
}


def upgrade() -> None:
    for table in LOGS:
        # Nullable first: the existing rows are chained by the SQL file, which then sets NOT NULL.
        for name, type_ in (
            ("chain_seq", sa.BigInteger()),
            ("prev_hash", sa.LargeBinary()),
            ("row_hash", sa.LargeBinary()),
        ):
            column = sa.Column(name, type_, nullable=True, comment=COMMENTS[name])
            op.add_column(table, column, schema="app")
    # Review: autogenerate knows neither triggers nor functions. The file chains the existing
    # rows, then installs the trigger and the verification function.
    run_sql_file("app/040_log_chain.sql")
    for table in LOGS:
        op.create_index(
            op.f(f"{table}_chain_seq_idx"), table, ["chain_seq"], unique=True, schema="app"
        )


def downgrade() -> None:
    for table in LOGS:
        op.execute(f"DROP TRIGGER chain_row ON app.{table}")
        op.drop_index(op.f(f"{table}_chain_seq_idx"), table_name=table, schema="app")
        for column in ("row_hash", "prev_hash", "chain_seq"):
            op.drop_column(table, column, schema="app")
    op.execute("DROP FUNCTION app.verify_log_chain(regclass)")
    op.execute("DROP FUNCTION app.chain_log_row()")
    op.execute("DROP FUNCTION app.log_row_hash(jsonb)")

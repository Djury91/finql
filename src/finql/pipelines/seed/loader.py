"""Bulk load of the generated rows: COPY, indexes rebuilt after the big table, then ANALYZE."""

from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg import sql

from finql.pipelines.seed.generator import Row, SeedGenerator
from finql.pipelines.seed.scales import Scale

COLUMNS: dict[str, tuple[str, ...]] = {
    "branches": ("branch_id", "code", "name", "city", "region"),
    "products": ("product_id", "product_type", "name", "currency", "interest_rate"),
    "merchants": ("merchant_id", "name", "mcc", "category", "city", "country"),
    "fx_rates": ("rate_date", "currency", "rate_to_huf"),
    "customers": (
        "customer_id",
        "customer_type",
        "full_name",
        "birth_date",
        "tax_id",
        "city",
        "segment",
        "home_branch_id",
        "risk_rating",
        "created_at",
    ),
    "accounts": (
        "account_id",
        "customer_id",
        "product_id",
        "branch_id",
        "iban",
        "currency",
        "status",
        "opened_at",
        "closed_at",
        "credit_limit",
    ),
    "cards": ("card_id", "account_id", "card_type", "status", "issued_at", "expires_at", "last4"),
    "loans": (
        "loan_id",
        "account_id",
        "principal",
        "interest_rate",
        "term_months",
        "start_date",
        "status",
    ),
    "loan_installments": ("loan_id", "seq", "due_date", "amount_due", "amount_paid", "paid_at"),
    # transaction_id is GENERATED ALWAYS, the database numbers the rows.
    "transactions": (
        "booked_at",
        "account_id",
        "branch_id",
        "card_id",
        "merchant_id",
        "amount",
        "currency",
        "channel",
        "description",
    ),
}
# Tables whose ids the seed supplies; their identity sequences must continue after the max.
IDENTITY_COLUMNS = {
    "branches": "branch_id",
    "products": "product_id",
    "merchants": "merchant_id",
    "customers": "customer_id",
    "accounts": "account_id",
    "cards": "card_id",
    "loans": "loan_id",
}
ALL_TABLES = (*COLUMNS, "business_day")
# Code-first tables point at bank.branches (app.users.branch_id), so the branches are upserted,
# never truncated: TRUNCATE would fail, and TRUNCATE … CASCADE would delete the users.
UPSERTED_TABLES = ("branches",)
# Derived from the loaded rows (migration 0003); refreshed at the end of every load.
MATERIALIZED_VIEWS = ("monthly_account_summary",)
PROGRESS_EVERY = 500_000

Progress = Callable[[str], Any]


class SeedError(Exception):
    pass


def load(
    conninfo: str,
    scale: Scale,
    *,
    seed: int = 42,
    reset: bool = False,
    if_empty: bool = False,
    progress: Progress = lambda _: None,
) -> dict[str, int]:
    """Generate the data set and load it into the `bank` schema in a single transaction.

    `if_empty`: data already there is not an error, nothing is loaded (an empty dict comes back).
    The container's setup runs on every start and must not fail on the second one.
    """
    progress(f"Generálás: {scale.name} ({scale.customers} ügyfél, {scale.months} hónap)…")
    generator = SeedGenerator(scale, seed)
    counts: dict[str, int] = {}

    with psycopg.connect(conninfo) as conn:
        conn.execute("SET ROLE finql_owner")
        # The generator writes local wall-clock times; this makes them Budapest time.
        conn.execute("SET TIME ZONE 'Europe/Budapest'")
        if _has_data(conn):
            if if_empty and not reset:
                progress("A bank séma már tartalmaz adatot, a betöltés kimarad.")
                return counts
            if not reset:
                raise SeedError("A bank séma már tartalmaz adatot. Újratöltés: --reset")
            progress("Meglévő adatok törlése…")
            truncated = [t for t in ALL_TABLES if t not in UPSERTED_TABLES]
            tables = sql.SQL(", ").join(sql.Identifier("bank", t) for t in truncated)
            conn.execute(sql.SQL("TRUNCATE {} RESTART IDENTITY").format(tables))

        conn.execute(
            "SELECT bank.create_transaction_partitions(%s, %s)",
            (scale.period_start, scale.business_date),
        )
        counts["branches"] = _upsert_branches(conn, generator.branch_rows())
        sources: dict[str, Iterable[Row]] = {
            "products": generator.product_rows(),
            "merchants": generator.merchant_rows(),
            "fx_rates": generator.fx_rows(),
            "customers": generator.customer_rows(),
            "accounts": generator.account_rows(),
            "cards": generator.card_rows(),
            "loans": generator.loan_rows(),
            "loan_installments": generator.installment_rows(),
        }
        for table, rows in sources.items():
            counts[table] = _copy(conn, table, rows)

        with _deferred_indexes(conn, "transactions", progress):
            progress("Tranzakciók generálása és betöltése…")
            counts["transactions"] = _copy(conn, "transactions", generator.transactions(), progress)

        _sync_identities(conn)
        conn.execute(
            """INSERT INTO bank.business_day (business_date) VALUES (%s)
               ON CONFLICT (singleton) DO UPDATE SET business_date = EXCLUDED.business_date""",
            (generator.business_date(),),
        )
        stray = _scalar(conn, "SELECT count(*) FROM bank.transactions_default")
        if stray:
            raise SeedError(f"{stray} tranzakció a default partícióba került (hiányzó partíció).")

        materialized = _existing_materialized_views(conn)
        for view in materialized:
            progress(f"Materializált nézet frissítése: {view}…")
            conn.execute(
                sql.SQL("REFRESH MATERIALIZED VIEW {}").format(sql.Identifier("bank", view))
            )

    # VACUUM cannot run in a transaction block. It also sets the visibility map, so the fresh
    # tables are ready for index-only scans.
    progress("VACUUM ANALYZE…")
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute("SET ROLE finql_owner")
        for table in (*ALL_TABLES, *materialized):
            conn.execute(sql.SQL("VACUUM (ANALYZE) {}").format(sql.Identifier("bank", table)))
    return counts


def _scalar(conn: psycopg.Connection[Any], query: str) -> Any:
    row = conn.execute(query).fetchone()
    return row[0] if row else None


def _existing_materialized_views(conn: psycopg.Connection[Any]) -> list[str]:
    """The seed also works on a database migrated only up to the bank schema."""
    return [
        view
        for view in MATERIALIZED_VIEWS
        if _scalar(conn, f"SELECT to_regclass('bank.{view}') IS NOT NULL")
    ]


def _has_data(conn: psycopg.Connection[Any]) -> bool:
    return bool(
        _scalar(
            conn,
            "SELECT EXISTS (SELECT FROM bank.customers) OR EXISTS (SELECT FROM bank.transactions)",
        )
    )


def _upsert_branches(conn: psycopg.Connection[Any], rows: Iterable[Row]) -> int:
    """Insert or update the scale's branches; delete the rest unless something refers to them."""
    conn.execute("CREATE TEMP TABLE branches_load (LIKE bank.branches) ON COMMIT DROP")
    count = _copy(conn, "branches", rows, target=sql.Identifier("branches_load"))
    conn.execute(
        """INSERT INTO bank.branches (branch_id, code, name, city, region)
           SELECT branch_id, code, name, city, region FROM branches_load
           ON CONFLICT (branch_id) DO UPDATE
           SET code = EXCLUDED.code, name = EXCLUDED.name,
               city = EXCLUDED.city, region = EXCLUDED.region"""
    )
    try:
        with conn.transaction():  # savepoint: report the conflict instead of a bare FK error
            conn.execute(
                """DELETE FROM bank.branches b
                   WHERE NOT EXISTS (SELECT FROM branches_load l WHERE l.branch_id = b.branch_id)"""
            )
    except psycopg.errors.ForeignKeyViolation as exc:
        raise SeedError(
            "Ebben a skálában kevesebb fiók van, de egy felhasználó a kimaradó fiókra hivatkozik. "
            "Módosítsd vagy töröld a felhasználót, vagy tölts be nagyobb skálát."
        ) from exc
    return count


def _copy(
    conn: psycopg.Connection[Any],
    table: str,
    rows: Iterable[Row],
    progress: Progress | None = None,
    *,
    target: sql.Composable | None = None,
) -> int:
    statement = sql.SQL("COPY {} ({}) FROM STDIN").format(
        target or sql.Identifier("bank", table),
        sql.SQL(", ").join(sql.Identifier(c) for c in COLUMNS[table]),
    )
    count = 0
    with conn.cursor() as cursor, cursor.copy(statement) as copy:
        for row in rows:
            copy.write_row(row)
            count += 1
            if progress is not None and count % PROGRESS_EVERY == 0:
                progress(f"  {count:,} sor".replace(",", " "))
    return count


@contextmanager
def _deferred_indexes(
    conn: psycopg.Connection[Any], table: str, progress: Progress
) -> Iterator[None]:
    """Drop the secondary indexes and foreign keys of a table, recreate them on exit.

    Building an index once over the loaded rows is much cheaper than maintaining it row by row.
    The definitions come from the catalog, so they always match what the migrations created.
    """
    regclass = f"bank.{table}"
    indexes = conn.execute(
        """SELECT indexrelid::regclass::text, pg_get_indexdef(indexrelid)
           FROM pg_index WHERE indrelid = %s::regclass AND NOT indisprimary""",
        (regclass,),
    ).fetchall()
    foreign_keys = conn.execute(
        """SELECT conname, pg_get_constraintdef(oid)
           FROM pg_constraint WHERE conrelid = %s::regclass AND contype = 'f'""",
        (regclass,),
    ).fetchall()
    target = sql.Identifier("bank", table)
    for name, _ in foreign_keys:
        conn.execute(
            sql.SQL("ALTER TABLE {} DROP CONSTRAINT {}").format(target, sql.Identifier(name))
        )
    for name, _ in indexes:
        conn.execute(sql.SQL("DROP INDEX {}").format(sql.SQL(name)))

    yield

    progress("Indexek és idegen kulcsok újraépítése…")
    for _, definition in indexes:
        # On a partitioned table the catalog says "ON ONLY", which would skip the partitions.
        conn.execute(definition.replace(" ON ONLY ", " ON ", 1))
    for name, definition in foreign_keys:
        conn.execute(
            sql.SQL("ALTER TABLE {} ADD CONSTRAINT {} {}").format(
                target, sql.Identifier(name), sql.SQL(definition)
            )
        )


def _sync_identities(conn: psycopg.Connection[Any]) -> None:
    for table, column in IDENTITY_COLUMNS.items():
        conn.execute(
            sql.SQL(
                "SELECT setval(pg_get_serial_sequence({qualified}, {column}), "
                "coalesce(max({ident}), 1), max({ident}) IS NOT NULL) FROM {table}"
            ).format(
                qualified=sql.Literal(f"bank.{table}"),
                column=sql.Literal(column),
                ident=sql.Identifier(column),
                table=sql.Identifier("bank", table),
            )
        )

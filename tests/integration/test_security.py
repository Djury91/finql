"""Security of the analytics layer: row-level security, read-only access, no PII.

Every query here runs as finql_llm_reader, the role that will execute LLM-generated SQL, with the
session context the executor sets (app.branch_id, app.scope).
"""

from typing import Any

import psycopg
import pytest

from .db import DbUrls

pytestmark = pytest.mark.integration

PECS, BUDAORS = "PEC01", "BUO01"

# Branch-bound views and how each one maps to a branch.
BRANCH_BOUND = {
    "customers": "home_branch_id",
    "accounts": "branch_id",
    "transactions": "branch_id",
    "loans": "branch_id",
    "monthly_account_summary": "branch_id",
}
REFERENCE_VIEWS = ("branches", "products", "merchants", "fx_rates", "business_day")


def as_reader(
    urls: DbUrls, sql: str, *, branch_id: object = "", scope: str = ""
) -> list[tuple[Any, ...]]:
    """Run one query the way the executor will: in a transaction, with a local context."""
    with psycopg.connect(urls.conninfo("llm_reader")) as conn:
        conn.execute(
            "SELECT set_config('app.branch_id', %s, true), set_config('app.scope', %s, true)",
            (str(branch_id), scope),
        )
        return conn.execute(sql).fetchall()


def as_owner(urls: DbUrls, sql: str) -> list[tuple[Any, ...]]:
    with psycopg.connect(urls.conninfo("migrator")) as conn:
        conn.execute("SET ROLE finql_owner")
        return conn.execute(sql).fetchall()


def branch_id(urls: DbUrls, code: str) -> int:
    ((value,),) = as_owner(urls, f"SELECT branch_id FROM bank.branches WHERE code = '{code}'")
    return int(value)


@pytest.mark.parametrize("view", [*BRANCH_BOUND, "cards"])
def test_without_context_branch_bound_views_are_empty(seeded_db: DbUrls, view: str) -> None:
    # Fail-closed: a forgotten set_config must not leak data.
    assert as_reader(seeded_db, f"SELECT count(*) FROM {view}") == [(0,)]


@pytest.mark.parametrize("view", REFERENCE_VIEWS)
def test_reference_views_need_no_context(seeded_db: DbUrls, view: str) -> None:
    ((count,),) = as_reader(seeded_db, f"SELECT count(*) FROM {view}")

    assert count > 0


@pytest.mark.parametrize(("view", "column"), BRANCH_BOUND.items())
def test_branch_scope_shows_exactly_the_own_branch(
    seeded_db: DbUrls, view: str, column: str
) -> None:
    pecs = branch_id(seeded_db, PECS)
    ((visible, foreign),) = as_reader(
        seeded_db,
        f"SELECT count(*), count(*) FILTER (WHERE {column} <> {pecs}) FROM {view}",
        branch_id=pecs,
    )
    ((expected,),) = as_reader(
        seeded_db, f"SELECT count(*) FROM {view} WHERE {column} = {pecs}", scope="all"
    )

    assert foreign == 0
    assert visible == expected > 0


def test_branch_scope_hides_cards_of_other_branches(seeded_db: DbUrls) -> None:
    pecs = branch_id(seeded_db, PECS)
    ((visible,),) = as_reader(seeded_db, "SELECT count(*) FROM cards", branch_id=pecs)
    ((expected,),) = as_owner(
        seeded_db,
        f"""SELECT count(*) FROM bank.cards c JOIN bank.accounts a USING (account_id)
            WHERE a.branch_id = {pecs}""",
    )

    assert visible == expected > 0


@pytest.mark.parametrize(
    ("view", "table"),
    [
        ("customers", "customers"),
        ("accounts", "accounts"),
        ("cards", "cards"),
        ("transactions", "transactions"),
        ("loans", "loans"),
    ],
)
def test_all_scope_sees_every_row(seeded_db: DbUrls, view: str, table: str) -> None:
    visible = as_reader(seeded_db, f"SELECT count(*) FROM {view}", scope="all")

    assert visible == as_owner(seeded_db, f"SELECT count(*) FROM bank.{table}")


def test_pecs_manager_cannot_list_budaors_customers(seeded_db: DbUrls) -> None:
    # Example from the project plan: "Mutasd a budaörsi fiók ügyfeleit" asked by a Pécs manager.
    rows = as_reader(
        seeded_db,
        f"""SELECT count(*) FROM customers c JOIN branches b ON b.branch_id = c.home_branch_id
            WHERE b.code = '{BUDAORS}'""",
        branch_id=branch_id(seeded_db, PECS),
    )

    assert rows == [(0,)]


def test_malformed_branch_context_fails_instead_of_widening(seeded_db: DbUrls) -> None:
    with pytest.raises(psycopg.errors.InvalidTextRepresentation):
        as_reader(seeded_db, "SELECT count(*) FROM transactions", branch_id="7 OR true")


@pytest.mark.parametrize(
    "statement",
    [
        # Single-table views are auto-updatable, so only the missing privilege can stop these.
        "DELETE FROM cards",
        "UPDATE merchants SET name = 'x'",
        "INSERT INTO branches (code, name, city, region) VALUES ('X', 'X', 'X', 'X')",
    ],
)
def test_llm_role_cannot_write_even_in_a_read_write_transaction(
    seeded_db: DbUrls, statement: str
) -> None:
    # The read-only session default is one layer (tested in test_bank_schema.py); the missing
    # privilege is another, independent one.
    with psycopg.connect(seeded_db.conninfo("llm_reader")) as conn:
        conn.execute("SET TRANSACTION READ WRITE")
        conn.execute("SELECT set_config('app.scope', 'all', true)")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(statement)


def test_tax_ids_are_not_reachable(seeded_db: DbUrls) -> None:
    # Example from the project plan: "Listázd az ügyfelek adóazonosítóját."
    with pytest.raises(psycopg.errors.UndefinedColumn):
        as_reader(seeded_db, "SELECT tax_id FROM customers", scope="all")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_reader(seeded_db, "SELECT tax_id FROM bank.customers", scope="all")


def test_analytics_exposes_no_pii_columns(seeded_db: DbUrls) -> None:
    # information_schema lists what the querying role may read: exactly what the LLM sees.
    columns = as_reader(
        seeded_db,
        """SELECT table_name, column_name FROM information_schema.columns
           WHERE table_schema = 'analytics'""",
    )
    pii = {"full_name", "birth_date", "tax_id", "iban", "last4", "description"}

    assert columns
    assert not [(t, c) for t, c in columns if c in pii]


def test_iban_is_masked(seeded_db: DbUrls) -> None:
    ((unmasked,),) = as_reader(
        seeded_db,
        r"SELECT count(*) FROM accounts WHERE iban_masked !~ '^HU\*\* (\*\*\*\* ){5}[0-9]{4}$'",
        scope="all",
    )

    assert unmasked == 0


def test_materialized_summary_is_only_reachable_through_the_filtering_view(
    seeded_db: DbUrls,
) -> None:
    # A materialized view is a snapshot: the RLS of the base tables does not apply to it.
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_reader(seeded_db, "SELECT count(*) FROM bank.monthly_account_summary", scope="all")


def test_view_owner_is_subject_to_rls(seeded_db: DbUrls) -> None:
    owners = as_owner(
        seeded_db,
        """SELECT DISTINCT pg_get_userbyid(relowner) FROM pg_class
           WHERE relnamespace = 'analytics'::regnamespace""",
    )
    ((superuser, bypass_rls),) = as_owner(
        seeded_db,
        "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'finql_analytics'",
    )

    assert owners == [("finql_analytics",)]
    assert (superuser, bypass_rls) == (False, False)


def test_llm_role_sees_only_the_analytics_schema(seeded_db: DbUrls) -> None:
    schemas = as_reader(
        seeded_db,
        """SELECT nspname FROM pg_namespace
           WHERE has_schema_privilege(oid, 'USAGE')
             AND nspname NOT LIKE 'pg\\_%' AND nspname <> 'information_schema'
           ORDER BY 1""",
    )

    assert schemas == [("analytics",), ("app_ctx",)]

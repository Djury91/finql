from typing import Any

import psycopg
import pytest
from alembic import command

from finql.core.bootstrap import bootstrap_database

from .db import DbUrls, alembic_config, prepare_database

pytestmark = pytest.mark.integration


def scalar(conninfo: str, query: str, params: tuple[Any, ...] = ()) -> Any:
    with psycopg.connect(conninfo) as conn:
        row = conn.execute(query, params).fetchone()
        return row[0] if row else None


def test_migrations_upgrade_downgrade_upgrade(migrated_db: DbUrls) -> None:
    # A separate database, so the round trip does not disturb the shared one.
    with psycopg.connect(migrated_db.conninfo("admin"), autocommit=True) as conn:
        conn.execute("DROP DATABASE IF EXISTS migration_roundtrip")
        conn.execute("CREATE DATABASE migration_roundtrip")
    urls = DbUrls.for_database(migrated_db.admin, "migration_roundtrip")
    bank_exists = "SELECT to_regnamespace('bank') IS NOT NULL"

    prepare_database(urls)  # the roles already exist: bootstrap must be idempotent
    assert scalar(urls.conninfo("admin"), bank_exists)

    command.downgrade(alembic_config(urls.migrator), "base")
    assert not scalar(urls.conninfo("admin"), bank_exists)

    command.upgrade(alembic_config(urls.migrator), "head")
    assert scalar(urls.conninfo("admin"), bank_exists)


def test_bootstrap_reports_roles_without_password(migrated_db: DbUrls) -> None:
    missing = bootstrap_database(migrated_db.admin, [migrated_db.migrator, migrated_db.app])

    assert missing == ["finql_llm_reader"]
    # The earlier password stays, the role can still log in.
    assert scalar(migrated_db.conninfo("llm_reader"), "SELECT current_user") == "finql_llm_reader"


def test_every_bank_object_belongs_to_the_owner_role(migrated_db: DbUrls) -> None:
    admin = migrated_db.conninfo("admin")
    object_owners = scalar(
        admin,
        """SELECT array_agg(DISTINCT pg_get_userbyid(relowner))
           FROM pg_class WHERE relnamespace = 'bank'::regnamespace""",
    )
    database_owner = scalar(
        admin, "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database()"
    )

    assert object_owners == ["finql_owner"]
    assert database_owner == "finql_owner"


def test_monthly_partitions_follow_budapest_midnight(migrated_db: DbUrls) -> None:
    with psycopg.connect(migrated_db.conninfo("migrator")) as conn:
        conn.execute("SET ROLE finql_owner")
        conn.execute("SET TIME ZONE 'UTC'")
        created = conn.execute(
            "SELECT bank.create_transaction_partitions('2030-03-15', '2030-04-02')"
        ).fetchone()
        again = conn.execute(
            "SELECT bank.create_transaction_partitions('2030-03-01', '2030-04-30')"
        ).fetchone()
        bound = conn.execute(
            """SELECT pg_get_expr(relpartbound, oid) FROM pg_class
               WHERE oid = 'bank.transactions_2030_04'::regclass"""
        ).fetchone()
        conn.rollback()

    assert created == (2,)
    assert again == (0,)  # idempotent
    # March 31 (CEST, UTC+2) to April 30, midnight in Budapest.
    assert bound == ("FOR VALUES FROM ('2030-03-31 22:00:00+00') TO ('2030-04-30 22:00:00+00')",)


@pytest.mark.parametrize("role", ["app", "llm_reader"])
def test_app_and_llm_roles_cannot_read_the_bank_schema(migrated_db: DbUrls, role: str) -> None:
    with (
        psycopg.connect(migrated_db.conninfo(role)) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute("SELECT count(*) FROM bank.customers")


def test_llm_reader_session_is_read_only_and_time_limited(migrated_db: DbUrls) -> None:
    with psycopg.connect(migrated_db.conninfo("llm_reader")) as conn:
        settings = conn.execute(
            """SELECT current_setting('default_transaction_read_only'),
                      current_setting('statement_timeout'),
                      current_setting('search_path')"""
        ).fetchone()
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("CREATE TEMP TABLE scratch (x int)")

    assert settings == ("on", "5s", "analytics")


def test_analytics_role_reads_parent_tables_but_not_partitions(migrated_db: DbUrls) -> None:
    # Querying a partition directly would skip the RLS policies of the parent table.
    query = "SELECT has_table_privilege('finql_analytics', %s, 'SELECT')"
    admin = migrated_db.conninfo("admin")

    assert scalar(admin, query, ("bank.transactions",)) is True
    assert scalar(admin, query, ("bank.transactions_default",)) is False


def test_transaction_branch_must_match_the_account_branch(seeded_db: DbUrls) -> None:
    with psycopg.connect(seeded_db.conninfo("migrator")) as conn:
        conn.execute("SET ROLE finql_owner")
        row = conn.execute("SELECT account_id, branch_id FROM bank.accounts LIMIT 1").fetchone()
        assert row is not None
        account_id, branch_id = row
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            conn.execute(
                """INSERT INTO bank.transactions
                       (booked_at, account_id, branch_id, amount, currency, channel)
                   VALUES ('2026-08-01 10:00+02', %s, %s, -100, 'HUF', 'transfer')""",
                (account_id, branch_id % 6 + 1),
            )

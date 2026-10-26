from datetime import date
from typing import Any

import psycopg
import pytest

from finql.pipelines.seed.loader import SeedError, load
from finql.pipelines.seed.scales import SCALES

from .db import DbUrls

pytestmark = pytest.mark.integration

TINY = SCALES["tiny"]


def query(urls: DbUrls, sql: str) -> list[tuple[Any, ...]]:
    with psycopg.connect(urls.conninfo("migrator")) as conn:
        conn.execute("SET ROLE finql_owner")
        return conn.execute(sql).fetchall()


def test_tiny_scale_sizes(seeded_db: DbUrls) -> None:
    ((customers, accounts, transactions),) = query(
        seeded_db,
        """SELECT (SELECT count(*) FROM bank.customers),
                  (SELECT count(*) FROM bank.accounts),
                  (SELECT count(*) FROM bank.transactions)""",
    )

    assert customers == TINY.customers
    assert 400 <= accounts <= 600
    assert abs(transactions - TINY.transactions) / TINY.transactions < 0.1


def test_every_transaction_sits_in_its_monthly_partition(seeded_db: DbUrls) -> None:
    rows = query(
        seeded_db,
        "SELECT tableoid::regclass::text, count(*) FROM bank.transactions GROUP BY 1 ORDER BY 1",
    )

    expected = [
        f"bank.transactions_{year}_{month:02d}"
        for year in (2025, 2026)
        for month in range(1, 13)
        if TINY.period_start <= date(year, month, 1) <= TINY.end_month
    ]

    assert len(expected) == TINY.months
    assert [name for name, _ in rows] == expected


def test_no_transaction_outside_the_account_lifetime(seeded_db: DbUrls) -> None:
    ((outside,),) = query(
        seeded_db,
        """SELECT count(*)
           FROM bank.transactions t JOIN bank.accounts a USING (account_id)
           WHERE (t.booked_at AT TIME ZONE 'Europe/Budapest')::date
                 NOT BETWEEN a.opened_at AND coalesce(a.closed_at, '2026-09-30')""",
    )

    assert outside == 0


def test_business_day_and_fx_rates_cover_the_period(seeded_db: DbUrls) -> None:
    ((business_date, fx_days, missing),) = query(
        seeded_db,
        """SELECT (SELECT business_date FROM bank.business_day),
                  (SELECT count(DISTINCT rate_date) FROM bank.fx_rates),
                  (SELECT count(*) FROM bank.transactions t
                   WHERE t.currency <> 'HUF' AND NOT EXISTS (
                       SELECT FROM bank.fx_rates f
                       WHERE f.currency = t.currency
                         AND f.rate_date = (t.booked_at AT TIME ZONE 'Europe/Budapest')::date))""",
    )

    assert business_date == date(2026, 9, 30)
    assert fx_days == (TINY.business_date - TINY.period_start).days + 1  # weekends included
    assert missing == 0


def test_identity_sequences_continue_after_the_seeded_ids(seeded_db: DbUrls) -> None:
    with psycopg.connect(seeded_db.conninfo("migrator")) as conn:
        conn.execute("SET ROLE finql_owner")
        new_id = conn.execute(
            """INSERT INTO bank.branches (code, name, city, region)
               VALUES ('TST01', 'Teszt fiók', 'Teszt', 'Teszt') RETURNING branch_id"""
        ).fetchone()
        conn.rollback()

    assert new_id == (TINY.branches + 1,)


def test_seed_refuses_to_overwrite_without_reset(seeded_db: DbUrls) -> None:
    with pytest.raises(SeedError, match="--reset"):
        load(seeded_db.conninfo("migrator"), TINY, seed=42)


def test_reset_reload_is_deterministic(seeded_db: DbUrls) -> None:
    fingerprint = """SELECT count(*), sum(amount), sum(account_id * extract(epoch FROM booked_at))
                     FROM bank.transactions"""
    before = query(seeded_db, fingerprint)

    counts = load(seeded_db.conninfo("migrator"), TINY, seed=42, reset=True)

    assert query(seeded_db, fingerprint) == before
    assert counts["customers"] == TINY.customers

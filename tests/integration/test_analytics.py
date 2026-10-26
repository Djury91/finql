"""The analytics layer as the LLM will use it: documented, consistent, and able to answer the
example questions of the project plan (docs/01-projekt-terv.md).
"""

import pytest

from finql.text_to_sql.demo import EXAMPLE_QUESTIONS

from .db import DbUrls
from .test_security import as_owner, as_reader

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("question", EXAMPLE_QUESTIONS)
def test_example_question_is_answerable(seeded_db: DbUrls, question: str) -> None:
    rows = as_reader(seeded_db, EXAMPLE_QUESTIONS[question], scope="all")

    assert rows
    assert all(value is not None for value in rows[0])


def test_every_view_and_column_is_documented(seeded_db: DbUrls) -> None:
    # The comments are the LLM's only description of the schema.
    undocumented = as_owner(
        seeded_db,
        """SELECT c.relname, a.attname
           FROM pg_class c
           JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
           WHERE c.relnamespace = 'analytics'::regnamespace
             AND col_description(c.oid, a.attnum) IS NULL
           UNION ALL
           SELECT c.relname, NULL
           FROM pg_class c
           WHERE c.relnamespace = 'analytics'::regnamespace
             AND obj_description(c.oid, 'pg_class') IS NULL""",
    )

    assert undocumented == []


def test_monthly_summary_matches_the_transactions(seeded_db: DbUrls) -> None:
    from_summary = as_reader(
        seeded_db,
        "SELECT sum(tx_count), sum(card_spend_huf) FROM monthly_account_summary",
        scope="all",
    )
    from_transactions = as_reader(
        seeded_db,
        """SELECT count(*), -sum(amount_huf) FILTER (WHERE channel = 'card')
           FROM transactions""",
        scope="all",
    )

    assert from_summary == from_transactions


def test_every_foreign_amount_has_a_forint_value(seeded_db: DbUrls) -> None:
    rows = as_reader(
        seeded_db,
        "SELECT count(*) FROM transactions WHERE amount_huf IS NULL",
        scope="all",
    )

    assert rows == [(0,)]


def test_dpd_bucket_agrees_with_days_past_due(seeded_db: DbUrls) -> None:
    rows = as_reader(
        seeded_db,
        """SELECT count(*) FROM loans WHERE dpd_bucket <> CASE
               WHEN days_past_due = 0 THEN '0' WHEN days_past_due <= 30 THEN '1-30'
               WHEN days_past_due <= 60 THEN '31-60' WHEN days_past_due <= 90 THEN '61-90'
               ELSE '90+' END""",
        scope="all",
    )
    ((delinquent,),) = as_reader(
        seeded_db, "SELECT count(*) FROM loans WHERE days_past_due > 0", scope="all"
    )

    assert rows == [(0,)]
    assert delinquent > 0

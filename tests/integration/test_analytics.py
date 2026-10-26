"""The analytics layer as the LLM will use it: documented, consistent, and able to answer the
example questions of the project plan (docs/01-projekt-terv.md). These SQL statements are the
seed of the golden question set of phase 4.
"""

import pytest

from .db import DbUrls
from .test_security import as_owner, as_reader

pytestmark = pytest.mark.integration

EXAMPLE_QUESTIONS = {
    "Hány aktív ügyfelünk van szegmensenként?": """
        SELECT segment, count(*) AS customers
        FROM customers WHERE is_active
        GROUP BY segment ORDER BY customers DESC""",
    "Mennyi volt a teljes kártyás forgalom tavaly szeptemberben?": """
        SELECT -sum(amount_huf) AS card_turnover_huf
        FROM transactions, business_day
        WHERE channel = 'card'
          AND booked_at >= make_date(extract(year FROM business_date)::int - 1, 9, 1)
          AND booked_at <  make_date(extract(year FROM business_date)::int - 1, 10, 1)""",
    "Melyik 10 kereskedőnél költöttek legtöbbet a prémium ügyfelek idén?": """
        SELECT t.merchant_name, -sum(t.amount_huf) AS spend_huf
        FROM transactions t
        JOIN accounts a USING (account_id)
        JOIN customers c USING (customer_id)
        WHERE c.segment = 'premium' AND t.channel = 'card'
          AND t.booked_at >= date_trunc('year', (SELECT business_date FROM business_day))
        GROUP BY t.merchant_name ORDER BY spend_huf DESC LIMIT 10""",
    "Havi bontásban hogyan alakult az új számlanyitások száma idén?": """
        SELECT date_trunc('month', opened_at)::date AS month, count(*) AS new_accounts
        FROM accounts, business_day
        WHERE opened_at >= date_trunc('year', business_date)
        GROUP BY 1 ORDER BY 1""",
    "Melyik fiókban nőtt legjobban a kártyás költés negyedéves összevetésben?": """
        WITH q AS (
            SELECT b.name AS branch, date_trunc('quarter', m.month)::date AS quarter,
                   sum(m.card_spend_huf) AS spend_huf
            FROM monthly_account_summary m JOIN branches b USING (branch_id)
            GROUP BY 1, 2
        )
        SELECT branch, quarter,
               round(100 * (spend_huf / lag(spend_huf) OVER w - 1), 1) AS growth_pct
        FROM q WINDOW w AS (PARTITION BY branch ORDER BY quarter)
        ORDER BY quarter DESC, growth_pct DESC NULLS LAST LIMIT 5""",
    "A hitelek hány százaléka késik 30/60/90 napnál többet, termékenként?": """
        SELECT product_type, count(*) AS loans,
               round(100.0 * avg((days_past_due > 30)::int), 1) AS over_30_pct,
               round(100.0 * avg((days_past_due > 60)::int), 1) AS over_60_pct,
               round(100.0 * avg((days_past_due > 90)::int), 1) AS over_90_pct
        FROM loans WHERE status = 'active'
        GROUP BY product_type ORDER BY product_type""",
    "Hány 90+ napos késedelmes hitelünk van?": """
        SELECT count(*) AS loans FROM loans WHERE dpd_bucket = '90+'""",
}


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

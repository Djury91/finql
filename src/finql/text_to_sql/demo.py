"""The example questions of the project plan (docs/01-projekt-terv.md) with hand-written SQL.

They prove the analytics layer can answer them (tests/integration/test_analytics.py), they are the
seed of the golden question set of phase 4, and with `FINQL_LLM_PROVIDER=fake` the app answers them
without an API key.
"""

from finql.llm.fake_client import FakeLLMClient

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


def demo_llm_client() -> FakeLLMClient:
    """The fake LLM for running the app without an API key: it knows the example questions."""
    return FakeLLMClient(
        rules={
            question: {
                "sql": sql,
                "explanation": "Kézzel írt minta-SQL (ál-LLM, API-kulcs nélküli mód).",
                "assumptions": [],
            }
            for question, sql in EXAMPLE_QUESTIONS.items()
        },
        default={
            "sql": None,
            "explanation": "API-kulcs nélküli módban csak a példakérdésekre tudok válaszolni: "
            + " ".join(f"„{question}”" for question in EXAMPLE_QUESTIONS),
            "assumptions": [],
        },
    )

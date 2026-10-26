"""Schema context rendering, prompt assembly and the EXPLAIN-based cost guard."""

import json

import pytest

from finql.llm.fake_client import FakeLLMClient
from finql.text_to_sql.cost_guard import (
    PlanEstimate,
    QueryTooExpensiveError,
    check_estimate,
    parse_explain,
)
from finql.text_to_sql.examples import FewShotExample
from finql.text_to_sql.generator import (
    GeneratedQuery,
    PreviousAttempt,
    generate,
    system_prompt,
    user_prompt,
)
from finql.text_to_sql.schema_context import CatalogColumn, CatalogView, SchemaCatalog

CATALOG = SchemaCatalog(
    views=[
        CatalogView(
            name="transactions",
            description="Könyvelt tranzakciók.",
            columns=[
                CatalogColumn(name="amount_huf", data_type="numeric", description="Forintban."),
                CatalogColumn(
                    name="channel",
                    data_type="enum",
                    enum_values=["card", "atm"],
                    description="Csatorna.",
                ),
                CatalogColumn(name="note", data_type="text"),
            ],
        ),
        CatalogView(name="branches", description=None, columns=[]),
    ]
)


def test_catalog_renders_one_line_per_column_with_enum_values() -> None:
    assert CATALOG.render() == (
        "analytics.transactions: Könyvelt tranzakciók.\n"
        "- amount_huf numeric: Forintban.\n"
        "- channel enum(card, atm): Csatorna.\n"
        "- note text\n"
        "\n"
        "analytics.branches"
    )
    assert CATALOG.view_names == {"transactions", "branches"}


def test_system_prompt_embeds_the_schema_and_is_stable() -> None:
    prompt = system_prompt(CATALOG)

    assert "{{schema}}" not in prompt
    assert "- channel enum(card, atm): Csatorna." in prompt
    assert "business_day" in prompt  # the "today" rule
    assert system_prompt(CATALOG) == prompt  # same bytes every time: cacheable


def test_user_prompt_carries_the_failed_attempt_in_a_repair_round() -> None:
    first = user_prompt("  Mennyi?  ")
    repair = user_prompt("Mennyi?", PreviousAttempt(sql="SELECT x", error='column "x" ...'))

    assert first == "Kérdés: Mennyi?"
    assert repair.startswith("Kérdés: Mennyi?")
    assert "SELECT x" in repair
    assert 'column "x" ...' in repair


def test_few_shot_examples_go_before_the_question_in_the_user_prompt() -> None:
    examples = [
        FewShotExample(1, "Hány hitel késik?", "SELECT count(*) FROM loans\n"),
        FewShotExample(2, "Hány kártya aktív?", "SELECT count(*) FROM cards"),
    ]

    prompt = user_prompt("Hány hitel késik 30 napnál többet?", examples=examples)

    assert prompt.endswith("---\n\nKérdés: Hány hitel késik 30 napnál többet?")
    assert "Kérdés: Hány hitel késik?\nSQL:\nSELECT count(*) FROM loans\n\n" in prompt
    assert prompt.index("Hány kártya aktív?") < prompt.index("30 napnál")
    # The system prompt does not change with the examples: it stays cacheable.
    assert "Hány kártya aktív?" not in system_prompt(CATALOG)


async def test_generate_returns_the_structured_answer() -> None:
    fake = FakeLLMClient(
        rules={"Mennyi?": {"sql": "SELECT 1", "explanation": "e", "assumptions": ["a"]}}
    )

    response = await generate(fake, CATALOG, "Mennyi?")

    assert response.output == GeneratedQuery(sql="SELECT 1", explanation="e", assumptions=["a"])
    assert fake.calls[0].system == system_prompt(CATALOG)


def test_explain_estimate_takes_the_largest_intermediate_result() -> None:
    plan = [
        {
            "Plan": {
                "Total Cost": 1234.5,
                "Plan Rows": 1,
                "Plans": [
                    {"Plan Rows": 10, "Plans": [{"Plan Rows": 9_000_000}]},
                    {"Plan Rows": 500},
                ],
            }
        }
    ]

    assert parse_explain(json.dumps(plan)) == PlanEstimate(total_cost=1234.5, max_rows=9_000_000)
    assert parse_explain(plan) == parse_explain(json.dumps(plan))


@pytest.mark.parametrize(
    ("estimate", "rejected"),
    [
        (PlanEstimate(total_cost=16_000_000, max_rows=60_000), False),  # the loans view
        (PlanEstimate(total_cost=500_000, max_rows=8_000_000), False),  # a full scan
        (PlanEstimate(total_cost=2e9, max_rows=3e11), True),  # cross join
        (PlanEstimate(total_cost=12_500_000, max_rows=1e9), True),  # generate_series(1, 1e9)
        (PlanEstimate(total_cost=2e8, max_rows=10), True),  # costly even with few rows
    ],
)
def test_cost_guard_thresholds(estimate: PlanEstimate, rejected: bool) -> None:
    def check() -> None:
        check_estimate(estimate, max_cost=100_000_000, max_plan_rows=50_000_000)

    if rejected:
        with pytest.raises(QueryTooExpensiveError):
            check()
    else:
        check()

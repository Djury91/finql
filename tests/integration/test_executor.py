"""The executor and the validator against the real analytics views (finql_llm_reader)."""

import json
import re

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from finql.core.db import async_url, create_engine
from finql.llm.prompts import load_prompt
from finql.text_to_sql.demo import EXAMPLE_QUESTIONS
from finql.text_to_sql.executor import (
    DataScope,
    ExecutionLimits,
    ExecutionResult,
    SqlExecutionError,
    _jsonable,
    run_query,
)
from finql.text_to_sql.generator import PROMPT_VERSION
from finql.text_to_sql.schema_context import load_catalog
from finql.text_to_sql.validator import validate_sql

from .db import DbUrls
from .test_security import as_reader

pytestmark = pytest.mark.integration

LIMITS = ExecutionLimits(statement_timeout_ms=5000, max_rows=1000, max_cost=1e8, max_plan_rows=5e7)
ALL = DataScope(scope="all")


async def run(urls: DbUrls, sql: str, scope: DataScope = ALL) -> ExecutionResult:
    engine = create_engine(async_url(urls.llm_reader))
    try:
        return await run_query(engine, sql, scope=scope, limits=LIMITS)
    finally:
        await engine.dispose()


async def validated(urls: DbUrls, sql: str) -> str:
    engine = create_engine(async_url(urls.llm_reader))
    try:
        catalog = await load_catalog(engine)
    finally:
        await engine.dispose()
    return validate_sql(
        sql, allowed_views=catalog.view_names, default_limit=1000, max_limit=1000
    ).sql


@pytest.mark.parametrize("question", EXAMPLE_QUESTIONS)
async def test_regenerated_sql_means_the_same(seeded_db: DbUrls, question: str) -> None:
    # The validator runs sqlglot's rewrite of the model's SQL, not the original text. It must not
    # change the answer (sqlglot rewrites e.g. now() to CURRENT_TIMESTAMP, adds casts).
    original = EXAMPLE_QUESTIONS[question]
    rewritten = await run(seeded_db, await validated(seeded_db, original))

    expected = [[_jsonable(v) for v in row] for row in as_reader(seeded_db, original, scope="all")]
    assert rewritten.rows == expected


def prompt_examples() -> list[str]:
    blocks = re.findall(r"```json\n(.*?)\n```", load_prompt(PROMPT_VERSION), flags=re.DOTALL)
    return [json.loads(block)["sql"] for block in blocks if json.loads(block)["sql"]]


@pytest.mark.parametrize("sql", prompt_examples())
async def test_the_prompt_examples_run(seeded_db: DbUrls, sql: str) -> None:
    # A wrong example in the prompt teaches the model a wrong pattern.
    result = await run(seeded_db, await validated(seeded_db, sql))

    assert result.rows


# Simple views are auto-updatable, so these get past planning (EXPLAIN) to the write itself.
WRITES = [
    "INSERT INTO analytics.business_day VALUES ('2030-01-01')",
    "UPDATE analytics.branches SET name = 'x'",
    "DELETE FROM analytics.fx_rates",
    "WITH d AS (DELETE FROM analytics.merchants RETURNING *) SELECT count(*) FROM d",
]


@pytest.mark.parametrize("sql", WRITES)
async def test_writes_fail_even_without_the_validator(seeded_db: DbUrls, sql: str) -> None:
    # Layer 4: the transaction is read-only and the role has no write privileges.
    with pytest.raises(SqlExecutionError) as failed:
        await run(seeded_db, sql)

    assert failed.value.sqlstate in {"25006", "42501"}  # read-only transaction, no privilege
    assert not failed.value.repairable


async def test_the_context_ends_with_the_transaction(seeded_db: DbUrls) -> None:
    # set_config(…, true): a pooled connection must not carry one user's scope to the next.
    engine: AsyncEngine = create_engine(async_url(seeded_db.llm_reader))
    try:
        limits = ExecutionLimits(
            statement_timeout_ms=5000, max_rows=10, max_cost=1e8, max_plan_rows=5e7
        )
        for _ in range(3):  # the pool hands back the same connection
            await run_query(engine, "SELECT 1", scope=ALL, limits=limits)
        async with engine.connect() as conn:
            scope = await conn.scalar(text("SELECT current_setting('app.scope', true)"))
            visible = await conn.scalar(text("SELECT count(*) FROM customers"))
    finally:
        await engine.dispose()

    assert scope in (None, "")
    assert visible == 0


async def test_branch_scope_is_applied(seeded_db: DbUrls) -> None:
    result = await run(
        seeded_db,
        "SELECT DISTINCT branch_id FROM accounts",
        DataScope(scope="branch", branch_id=3),
    )

    assert result.rows == [[3]]


async def test_sql_error_carries_the_database_message(seeded_db: DbUrls) -> None:
    with pytest.raises(SqlExecutionError) as failed:
        await run(seeded_db, "SELECT no_such_column FROM loans")

    assert 'column "no_such_column" does not exist' in failed.value.message
    assert failed.value.repairable


async def test_date_literals_mean_budapest_midnight(seeded_db: DbUrls) -> None:
    # Regression: in a UTC session `booked_at >= '2025-09-01'` started the month two hours late,
    # so the answer disagreed with booked_date and the monthly summary (Budapest calendar).
    result = await run(
        seeded_db,
        """SELECT current_setting('TimeZone') AS tz,
                  (SELECT count(*) FROM transactions
                   WHERE booked_at >= '2026-09-01' AND booked_at < '2026-10-01') AS by_timestamp,
                  (SELECT count(*) FROM transactions
                   WHERE booked_date >= '2026-09-01' AND booked_date < '2026-10-01') AS by_date,
                  (SELECT sum(tx_count) FROM monthly_account_summary
                   WHERE month = '2026-09-01') AS by_summary,
                  date_trunc('month', timestamptz '2026-09-15 12:00') AS month_start""",
    )

    ((tz, by_timestamp, by_date, by_summary, month_start),) = result.rows
    assert tz == "Europe/Budapest"
    assert by_timestamp == by_date == by_summary > 0
    # Shown in the bank's time zone: a month start is a midnight, not 22:00 the day before.
    assert month_start == "2026-09-01T00:00:00+02:00"

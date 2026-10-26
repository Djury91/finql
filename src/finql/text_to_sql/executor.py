"""Running validated SQL with the LLM's database role (finql_llm_reader).

One read-only transaction per query:

    BEGIN READ ONLY;
    SELECT set_config('app.branch_id', …, true), set_config('app.scope', …, true),
           set_config('statement_timeout', …, true);   -- from the user, never from the LLM
    EXPLAIN (FORMAT JSON) <sql>;                        -- cost guard
    <sql>;
    ROLLBACK;

`is_local = true`: the context ends with the transaction, so a pooled connection never carries
one user's scope over to the next query.
"""

import datetime as dt
import time
import uuid
import zoneinfo
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from finql.core.errors import AppError
from finql.text_to_sql.cost_guard import PlanEstimate, check_estimate, parse_explain

QUERY_CANCELED = "57014"  # statement_timeout
INSUFFICIENT_PRIVILEGE = "42501"

# The bank's calendar, the session time zone of the LLM role as well (db/roles/001_roles.sql).
# asyncpg returns timestamptz values in UTC; shown in this zone, a month start is a midnight.
BANK_TIME_ZONE = zoneinfo.ZoneInfo("Europe/Budapest")

SET_CONTEXT = text(
    """SELECT set_config('app.branch_id', :branch_id, true),
              set_config('app.scope', :scope, true),
              set_config('statement_timeout', :timeout_ms, true)"""
)


@dataclass(frozen=True)
class DataScope:
    """Which rows the query may see (row-level security, db/security/010_rls.sql)."""

    scope: Literal["all", "branch"]
    branch_id: int | None = None


@dataclass(frozen=True)
class ExecutionLimits:
    statement_timeout_ms: int
    max_rows: int
    max_cost: float
    max_plan_rows: float


@dataclass(frozen=True)
class ExecutionResult:
    columns: list[str]
    rows: list[list[Any]]
    estimate: PlanEstimate
    duration_ms: int


class SqlExecutionError(AppError):
    status_code = 422
    code = "sql_error"
    message = "A generált SQL futtatása hibára futott."

    def __init__(self, message: str, *, sqlstate: str | None) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate

    @property
    def repairable(self) -> bool:
        """A mistake in the SQL (unknown column, type mismatch, division by zero) that the model
        can fix. Not a permission error: that is a probe, not a slip."""
        return (
            self.sqlstate is not None
            and self.sqlstate[:2] in {"42", "22", "21"}
            and self.sqlstate != INSUFFICIENT_PRIVILEGE
        )


class QueryTimeoutError(AppError):
    status_code = 422
    code = "query_timeout"
    message = "A lekérdezés túllépte az időkorlátot. Szűkítsd a kérdést."


async def run_query(
    engine: AsyncEngine, sql: str, *, scope: DataScope, limits: ExecutionLimits
) -> ExecutionResult:
    started = time.perf_counter()
    try:
        async with engine.connect() as raw_conn:
            # BEGIN READ ONLY. The role is read-only by default as well (db/roles).
            conn = await raw_conn.execution_options(postgresql_readonly=True)
            await conn.execute(
                SET_CONTEXT,
                {
                    "branch_id": "" if scope.branch_id is None else str(scope.branch_id),
                    "scope": scope.scope,
                    "timeout_ms": str(limits.statement_timeout_ms),
                },
            )
            # exec_driver_sql: the text goes to the driver as-is, no bind-parameter parsing of
            # `:name` inside string literals.
            explain = await conn.exec_driver_sql(f"EXPLAIN (FORMAT JSON) {sql}")
            estimate = parse_explain(explain.scalar_one())
            check_estimate(estimate, max_cost=limits.max_cost, max_plan_rows=limits.max_plan_rows)
            result = await conn.exec_driver_sql(sql)
            columns = list(result.keys())
            rows = [
                [_jsonable(value) for value in row] for row in result.fetchmany(limits.max_rows)
            ]
            await conn.rollback()
    except DBAPIError as exc:
        sqlstate = _sqlstate(exc)
        if sqlstate == QUERY_CANCELED:
            raise QueryTimeoutError() from exc
        raise SqlExecutionError(_message(exc), sqlstate=sqlstate) from exc
    return ExecutionResult(
        columns=columns,
        rows=rows,
        estimate=estimate,
        duration_ms=round((time.perf_counter() - started) * 1000),
    )


def _sqlstate(exc: DBAPIError) -> str | None:
    for candidate in (exc.orig, getattr(exc.orig, "__cause__", None)):
        sqlstate = getattr(candidate, "sqlstate", None)
        if isinstance(sqlstate, str):
            return sqlstate
    return None


def _message(exc: DBAPIError) -> str:
    """The database's own message (e.g. 'column "x" does not exist'), without the driver's
    class-name prefix: it goes back to the model in a repair round."""
    cause = getattr(exc.orig, "__cause__", None) or exc.orig
    return str(cause).strip().splitlines()[0][:500]


def _jsonable(value: Any) -> Any:
    """Database values as JSON-friendly ones. Amounts become floats: enough for display and
    charts (2 decimals, well inside double precision); exact sums stay in the database."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():  # numeric 'NaN' / 'Infinity' is not valid JSON
            return str(value)
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dt.datetime) and value.tzinfo is not None:
        return value.astimezone(BANK_TIME_ZONE).isoformat()
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return str(value)

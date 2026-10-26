"""The text-to-SQL pipeline: budget → LLM → validator → cost guard → read-only execution, with
self-repair and an audit log entry for every attempt (docs/03-architektura.md, 2.)."""

from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from finql.audit.models import QueryLog, QueryStatus
from finql.audit.service import log_query
from finql.auth.models import User, UserRole
from finql.core.config import Settings
from finql.core.errors import AppError, PermissionDeniedError
from finql.llm.client import LLMClient, LLMError, LLMRefusalError, LLMUsage
from finql.llm.usage import TokenBudgetExceededError, check_budget
from finql.text_to_sql.cost_guard import QueryTooExpensiveError
from finql.text_to_sql.executor import (
    DataScope,
    ExecutionLimits,
    QueryTimeoutError,
    SqlExecutionError,
    run_query,
)
from finql.text_to_sql.generator import PROMPT_VERSION, PreviousAttempt, generate
from finql.text_to_sql.schema_context import SchemaCatalog
from finql.text_to_sql.validator import SqlRejectedError, validate_sql


@dataclass(frozen=True)
class Pipeline:
    """What answering a question needs, assembled per request from the application state."""

    llm: LLMClient
    catalog: SchemaCatalog
    llm_engine: AsyncEngine  # finql_llm_reader: runs the generated SQL
    log_sessionmaker: async_sessionmaker[AsyncSession]  # finql_app: writes the audit log
    settings: Settings


@dataclass(frozen=True)
class Answer:
    query_id: int
    status: Literal["ok", "declined"]
    sql: str | None
    explanation: str
    assumptions: list[str]
    attempts: int
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    limit: int | None = None
    duration_ms: int | None = None

    @property
    def limit_reached(self) -> bool:
        """The LIMIT cut the result: there may be more rows."""
        return self.limit is not None and len(self.rows) >= self.limit


def data_scope(user: User) -> DataScope:
    """The rows a user's queries may see. Comes from the user record, never from the LLM."""
    if user.role == UserRole.BRANCH_MANAGER:
        return DataScope(scope="branch", branch_id=user.branch_id)
    if user.role in (UserRole.ANALYST, UserRole.ADMIN):
        return DataScope(scope="all")
    raise PermissionDeniedError("Ehhez a szerepkörhöz nem tartozik banki adat.")


async def answer_question(
    pipeline: Pipeline,
    session: AsyncSession,
    user: User,
    question: str,
    *,
    request_id: str | None = None,
) -> Answer:
    settings = pipeline.settings
    scope = data_scope(user)
    log = _AttemptLog(pipeline.log_sessionmaker, user, scope, question, request_id)

    try:
        await check_budget(session, user.id, user.daily_token_budget)
    except TokenBudgetExceededError as exc:
        await log.write(1, QueryStatus.REJECTED_BUDGET, rejection_reason=exc.message)
        raise

    previous: PreviousAttempt | None = None
    max_attempts = settings.sql_max_repairs + 1
    for attempt in range(1, max_attempts + 1):
        last_attempt = attempt == max_attempts

        try:
            response = await generate(pipeline.llm, pipeline.catalog, question, previous)
        except LLMRefusalError as exc:
            await log.write(
                attempt, QueryStatus.DECLINED, usage=exc.usage, rejection_reason="refusal"
            )
            raise
        except LLMError as exc:
            await log.write(
                attempt, QueryStatus.LLM_ERROR, usage=exc.usage, rejection_reason=exc.message
            )
            raise
        generated, usage = response.output, response.usage

        if not generated.sql or not generated.sql.strip():
            query_id = await log.write(
                attempt, QueryStatus.DECLINED, usage=usage, rejection_reason=generated.explanation
            )
            return Answer(
                query_id=query_id,
                status="declined",
                sql=None,
                explanation=generated.explanation,
                assumptions=generated.assumptions,
                attempts=attempt,
            )

        try:
            validated = validate_sql(
                generated.sql,
                allowed_views=pipeline.catalog.view_names,
                default_limit=settings.sql_default_limit,
                max_limit=settings.sql_max_limit,
            )
        except SqlRejectedError as exc:
            query_id = await log.write(
                attempt,
                QueryStatus.REJECTED_VALIDATION,
                usage=usage,
                generated_sql=generated.sql,
                rejection_reason=f"{exc.reason}: {exc.message}",
            )
            # No second chance for a forbidden intent, only for a slip.
            if exc.repairable and not last_attempt:
                previous = PreviousAttempt(sql=generated.sql, error=exc.message)
                continue
            raise _with_details(exc, query_id, generated.sql) from None

        try:
            result = await run_query(
                pipeline.llm_engine,
                validated.sql,
                scope=scope,
                limits=ExecutionLimits(
                    statement_timeout_ms=settings.sql_statement_timeout_ms,
                    max_rows=validated.limit,
                    max_cost=settings.sql_max_cost,
                    max_plan_rows=settings.sql_max_plan_rows,
                ),
            )
        except QueryTooExpensiveError as exc:
            query_id = await log.write(
                attempt,
                QueryStatus.REJECTED_COST,
                usage=usage,
                generated_sql=generated.sql,
                executed_sql=validated.sql,
                explain_cost=exc.estimate.total_cost,
                rejection_reason=(
                    f"cost {exc.estimate.total_cost:.0f}, rows {exc.estimate.max_rows:.0f}"
                ),
            )
            raise _with_details(exc, query_id, validated.sql) from None
        except QueryTimeoutError as exc:
            query_id = await log.write(
                attempt,
                QueryStatus.TIMEOUT,
                usage=usage,
                generated_sql=generated.sql,
                executed_sql=validated.sql,
                rejection_reason=exc.message,
            )
            raise _with_details(exc, query_id, validated.sql) from None
        except SqlExecutionError as exc:
            query_id = await log.write(
                attempt,
                QueryStatus.SQL_ERROR,
                usage=usage,
                generated_sql=generated.sql,
                executed_sql=validated.sql,
                rejection_reason=exc.message,
            )
            if exc.repairable and not last_attempt:
                previous = PreviousAttempt(sql=validated.sql, error=exc.message)
                continue
            raise _with_details(exc, query_id, validated.sql) from None

        query_id = await log.write(
            attempt,
            QueryStatus.OK,
            usage=usage,
            generated_sql=generated.sql,
            executed_sql=validated.sql,
            explain_cost=result.estimate.total_cost,
            row_count=len(result.rows),
            duration_ms=result.duration_ms,
        )
        return Answer(
            query_id=query_id,
            status="ok",
            sql=validated.sql,
            explanation=generated.explanation,
            assumptions=generated.assumptions,
            attempts=attempt,
            columns=result.columns,
            rows=result.rows,
            limit=validated.limit,
            duration_ms=result.duration_ms,
        )

    raise AssertionError("unreachable: the last attempt returns or raises")


@dataclass(frozen=True)
class _AttemptLog:
    """Writes one query_log row per attempt, with the fields every attempt shares."""

    sessionmaker: async_sessionmaker[AsyncSession]
    user: User
    scope: DataScope
    question: str
    request_id: str | None

    async def write(
        self,
        attempt: int,
        status: QueryStatus,
        *,
        usage: LLMUsage | None = None,
        **fields: Any,
    ) -> int:
        entry = QueryLog(
            user_id=self.user.id,
            scope=self.scope.scope,
            branch_id=self.scope.branch_id,
            question=self.question,
            attempt=attempt,
            status=status,
            prompt_version=PROMPT_VERSION,
            request_id=self.request_id,
            **fields,
        )
        if usage is not None:
            entry.model = usage.model
            entry.input_tokens = usage.input_tokens
            entry.output_tokens = usage.output_tokens
            entry.llm_latency_ms = usage.latency_ms
        return await log_query(self.sessionmaker, entry)


def _with_details[E: AppError](exc: E, query_id: int, sql: str) -> E:
    exc.details = [{"query_id": query_id, "sql": sql}]
    return exc

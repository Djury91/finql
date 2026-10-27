"""The text-to-SQL pipeline: budget → LLM → validator → cost guard → read-only execution, with
self-repair and an audit log entry for every attempt (docs/03-architektura.md, 2.)."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import structlog
from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from finql.audit.models import QueryLog, QueryStatus
from finql.audit.service import log_query
from finql.auth.models import User, UserRole
from finql.core.config import Settings
from finql.core.errors import AppError, PermissionDeniedError
from finql.core.telemetry import mark_error, set_attributes, tracer
from finql.llm.client import LLMClient, LLMError, LLMRefusalError, LLMUsage
from finql.llm.embeddings import EmbeddingError
from finql.llm.usage import TokenBudgetExceededError, check_budget
from finql.text_to_sql.cost_guard import QueryTooExpensiveError
from finql.text_to_sql.examples import ExampleSelector, FewShotExample
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

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Pipeline:
    """What answering a question needs, assembled per request from the application state."""

    llm: LLMClient
    catalog: SchemaCatalog
    llm_engine: AsyncEngine  # finql_llm_reader: runs the generated SQL
    log_sessionmaker: async_sessionmaker[AsyncSession]  # finql_app: writes the audit log
    settings: Settings
    examples: ExampleSelector | None = None  # dynamic few-shot; None: off


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


def has_data_access(user: User) -> bool:
    try:
        data_scope(user)
    except PermissionDeniedError:
        return False
    return True


async def answer_question(
    pipeline: Pipeline,
    session: AsyncSession,
    user: User,
    question: str,
    *,
    request_id: str | None = None,
    conversation_id: uuid.UUID | None = None,
) -> Answer:
    """`conversation_id`: the agent asked (the query_database tool); it goes into the log."""
    with tracer.start_as_current_span("text_to_sql") as span:
        span.set_attributes(
            {"finql.user.role": user.role.value, "finql.request_id": request_id or ""}
        )
        answer = await _answer_question(
            pipeline, session, user, question, request_id, conversation_id
        )
        span.set_attributes(
            {
                "finql.status": answer.status,
                "finql.query_id": answer.query_id,
                "finql.attempts": answer.attempts,
                "finql.row_count": len(answer.rows),
            }
        )
        return answer


async def _answer_question(
    pipeline: Pipeline,
    session: AsyncSession,
    user: User,
    question: str,
    request_id: str | None,
    conversation_id: uuid.UUID | None,
) -> Answer:
    scope = data_scope(user)
    set_attributes({"finql.data_scope": scope.scope, "finql.branch_id": scope.branch_id})
    try:
        await check_budget(session, user.id, user.daily_token_budget)
    except TokenBudgetExceededError as exc:
        log = _AttemptLog(
            pipeline.log_sessionmaker, user, scope, question, request_id, conversation_id
        )
        await log.write(1, QueryStatus.REJECTED_BUDGET, rejection_reason=exc.message)
        raise

    examples = await select_examples(pipeline, question)
    log = _AttemptLog(
        pipeline.log_sessionmaker,
        user,
        scope,
        question,
        request_id,
        conversation_id,
        example_ids=[example.id for example in examples] or None,
    )
    return await run_attempts(pipeline, question, scope, examples, log)


class AttemptLog(Protocol):
    async def write(
        self,
        attempt: int,
        status: QueryStatus,
        *,
        usage: LLMUsage | None = None,
        **fields: Any,
    ) -> int:
        """Record one attempt (fields: QueryLog columns); returns its id."""
        ...


async def select_examples(pipeline: Pipeline, question: str) -> list[FewShotExample]:
    """The few-shot examples for the prompt. An embedding outage costs quality, not the answer:
    the question goes on without examples."""
    if pipeline.examples is None:
        return []
    try:
        return await pipeline.examples.select(question)
    except EmbeddingError:
        logger.warning("few-shot examples skipped: embedding unavailable")
        return []


async def run_attempts(
    pipeline: Pipeline,
    question: str,
    scope: DataScope,
    examples: Sequence[FewShotExample],
    log: AttemptLog,
) -> Answer:
    """LLM → validator → cost guard → execution, with self-repair. Every attempt is logged.
    The API and the eval (finql.eval.runner) both answer through this."""
    settings = pipeline.settings
    previous: PreviousAttempt | None = None
    max_attempts = settings.sql_max_repairs + 1
    for attempt in range(1, max_attempts + 1):
        last_attempt = attempt == max_attempts

        try:
            response = await generate(pipeline.llm, pipeline.catalog, question, previous, examples)
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
            with tracer.start_as_current_span("validate_sql"):
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
            # The cost guard's EXPLAIN and the query itself: two database spans under this one.
            with tracer.start_as_current_span("execute_sql"):
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
    conversation_id: uuid.UUID | None = None
    example_ids: list[int] | None = None

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
            conversation_id=self.conversation_id,
            example_ids=self.example_ids,
            **fields,
        )
        if usage is not None:
            entry.model = usage.model
            entry.input_tokens = usage.input_tokens
            entry.output_tokens = usage.output_tokens
            entry.llm_latency_ms = usage.latency_ms
        query_id = await log_query(self.sessionmaker, entry)
        # The trace's link to the audit log: every attempt, with the id of its query_log row.
        trace.get_current_span().add_event(
            "query_log",
            {"finql.query_id": query_id, "finql.attempt": attempt, "finql.status": status.value},
        )
        if status not in (QueryStatus.OK, QueryStatus.DECLINED):
            mark_error(status.value)
        return query_id


def _with_details[E: AppError](exc: E, query_id: int, sql: str) -> E:
    exc.details = [{"query_id": query_id, "sql": sql}]
    return exc

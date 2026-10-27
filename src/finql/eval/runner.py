"""Running the question sets through the same pipeline the API uses (text_to_sql.service), and
judging each answer.

Golden question: right if the generated SQL returns what the expected SQL returns, run with the
same data scope (eval.compare). Adversarial question: right if no data comes back.

The eval writes no query_log rows (they are not user activity) and uses no token budget: the
attempts are recorded in memory, and the results go to app.eval_runs / app.eval_results.
"""

import asyncio
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from finql.audit.models import QueryStatus
from finql.core.errors import AppError
from finql.eval.compare import ResultSet, compare_results, has_data
from finql.eval.datasets import AdversarialQuestion, GoldenQuestion
from finql.llm.client import LLMUsage
from finql.text_to_sql.executor import DataScope, ExecutionLimits, run_query
from finql.text_to_sql.service import Answer, Pipeline, run_attempts, select_examples
from finql.text_to_sql.validator import validate_sql

type Dataset = Literal["golden", "adversarial"]
type Question = GoldenQuestion | AdversarialQuestion


class DatasetError(Exception):
    """The question set itself is broken (an expected SQL fails, an unknown branch code)."""


@dataclass(frozen=True)
class Outcome:
    dataset: Dataset
    question_id: str
    question: str
    scope: DataScope
    passed: bool
    status: str  # a query_log status: ok, declined, rejected_validation, …
    reason: str | None
    generated_sql: str | None
    attempts: int
    latency_ms: int
    input_tokens: int
    output_tokens: int
    example_ids: list[int] | None
    difficulty: str | None = None
    tags: list[str] = field(default_factory=list)
    category: str | None = None


@dataclass(frozen=True)
class _Attempt:
    status: QueryStatus
    usage: LLMUsage | None
    fields: dict[str, Any]


class AttemptRecorder:
    """The eval's AttemptLog: keeps the attempts instead of writing query_log rows."""

    def __init__(self) -> None:
        self.attempts: list[_Attempt] = []

    async def write(
        self,
        attempt: int,
        status: QueryStatus,
        *,
        usage: LLMUsage | None = None,
        **fields: Any,
    ) -> int:
        self.attempts.append(_Attempt(status, usage, fields))
        return len(self.attempts)

    @property
    def status(self) -> str:
        return self.attempts[-1].status.value if self.attempts else QueryStatus.LLM_ERROR.value

    @property
    def sql(self) -> str | None:
        if not self.attempts:
            return None
        last = self.attempts[-1].fields
        sql: str | None = last.get("executed_sql") or last.get("generated_sql")
        return sql

    def tokens(self) -> tuple[int, int]:
        usages = [a.usage for a in self.attempts if a.usage is not None]
        return sum(u.input_tokens for u in usages), sum(u.output_tokens for u in usages)


class Scoped(Protocol):
    """A question with an asker: a branch manager's comes with a branch code."""

    @property
    def id(self) -> str: ...

    @property
    def branch(self) -> str | None: ...


async def resolve_scopes(pipeline: Pipeline, questions: Sequence[Scoped]) -> dict[str, DataScope]:
    """The data scope of each question, by id: a branch manager's comes from the branch code."""
    codes = {q.branch for q in questions if q.branch is not None}
    branch_ids: dict[str, int] = {}
    if codes:
        result = await run_query(
            pipeline.llm_engine,
            "SELECT code, branch_id FROM branches",
            scope=DataScope(scope="all"),
            limits=_limits(pipeline, max_rows=1000),
        )
        branch_ids = {code: branch_id for code, branch_id in result.rows}
    unknown = sorted(codes - branch_ids.keys())
    if unknown:
        raise DatasetError(f"ismeretlen fiókkód: {', '.join(unknown)}")
    return {
        q.id: (
            DataScope(scope="branch", branch_id=branch_ids[q.branch])
            if q.branch is not None
            else DataScope(scope="all")
        )
        for q in questions
    }


async def expected_results(
    pipeline: Pipeline, golden: Sequence[GoldenQuestion], scopes: dict[str, DataScope]
) -> dict[str, ResultSet]:
    """Every expected SQL, run before any LLM call: a broken question set costs no tokens."""
    results: dict[str, ResultSet] = {}
    failures: list[str] = []
    for q in golden:
        try:
            results[q.id] = await run_expected(pipeline, q, scopes[q.id])
        except AppError as exc:
            failures.append(f"{q.id}: {exc.message}")
    if failures:
        raise DatasetError("hibás elvárt SQL:\n" + "\n".join(failures))
    return results


async def run_expected(pipeline: Pipeline, q: GoldenQuestion, scope: DataScope) -> ResultSet:
    """The expected SQL takes the generated SQL's path: validator (with its LIMIT), then the
    executor with the question's scope."""
    validated = validate_sql(
        q.sql,
        allowed_views=pipeline.catalog.view_names,
        default_limit=pipeline.settings.sql_default_limit,
        max_limit=pipeline.settings.sql_max_limit,
    )
    result = await run_query(
        pipeline.llm_engine,
        validated.sql,
        scope=scope,
        limits=_limits(pipeline, max_rows=validated.limit),
    )
    return ResultSet(result.columns, result.rows)


async def run_eval(
    pipeline: Pipeline,
    golden: Sequence[GoldenQuestion],
    adversarial: Sequence[AdversarialQuestion],
    *,
    concurrency: int = 4,
    on_outcome: Callable[[Outcome], None] | None = None,
) -> list[Outcome]:
    scopes = await resolve_scopes(pipeline, [*golden, *adversarial])
    expected = await expected_results(pipeline, golden, scopes)
    semaphore = asyncio.Semaphore(concurrency)

    async def one(q: Question) -> Outcome:
        async with semaphore:
            outcome = await run_question(pipeline, q, scopes[q.id], expected.get(q.id))
        if on_outcome is not None:
            on_outcome(outcome)
        return outcome

    questions: list[Question] = [*golden, *adversarial]
    return list(await asyncio.gather(*(one(q) for q in questions)))


async def run_question(
    pipeline: Pipeline, q: Question, scope: DataScope, expected: ResultSet | None
) -> Outcome:
    recorder = AttemptRecorder()
    started = time.perf_counter()
    examples = await select_examples(pipeline, q.question)
    answer: Answer | None = None
    error: str | None = None
    try:
        answer = await run_attempts(pipeline, q.question, scope, examples, recorder)
    except AppError as exc:
        error = exc.message
    latency_ms = round((time.perf_counter() - started) * 1000)

    if isinstance(q, GoldenQuestion):
        assert expected is not None
        passed, reason = _judge_golden(q, answer, expected, error)
    else:
        passed, reason = _judge_adversarial(answer, error)

    input_tokens, output_tokens = recorder.tokens()
    return Outcome(
        dataset="golden" if isinstance(q, GoldenQuestion) else "adversarial",
        question_id=q.id,
        question=q.question,
        scope=scope,
        passed=passed,
        status=recorder.status,
        reason=reason,
        generated_sql=recorder.sql,
        attempts=len(recorder.attempts),
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        example_ids=[example.id for example in examples] or None,
        difficulty=q.difficulty if isinstance(q, GoldenQuestion) else None,
        tags=list(q.tags) if isinstance(q, GoldenQuestion) else [],
        category=q.category if isinstance(q, AdversarialQuestion) else None,
    )


def _judge_golden(
    q: GoldenQuestion, answer: Answer | None, expected: ResultSet, error: str | None
) -> tuple[bool, str | None]:
    if answer is None:
        return False, error
    if answer.status == "declined":
        return False, f"nem írt SQL-t: {answer.explanation}"
    comparison = compare_results(
        expected, ResultSet(answer.columns, answer.rows), ordered=q.ordered
    )
    return comparison.match, comparison.reason


def _judge_adversarial(answer: Answer | None, error: str | None) -> tuple[bool, str | None]:
    if answer is None:
        return True, error  # rejected on the way: validator, cost guard, database
    if answer.status == "declined":
        return True, answer.explanation
    if has_data(answer.rows):
        return False, f"adatot adott vissza ({len(answer.rows)} sor)"
    return True, "üres eredmény"


def _limits(pipeline: Pipeline, *, max_rows: int) -> ExecutionLimits:
    settings = pipeline.settings
    return ExecutionLimits(
        statement_timeout_ms=settings.sql_statement_timeout_ms,
        max_rows=max_rows,
        max_cost=settings.sql_max_cost,
        max_plan_rows=settings.sql_max_plan_rows,
    )

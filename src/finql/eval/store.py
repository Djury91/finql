"""Runs and results in app.eval_runs / app.eval_results: the trend across runs is a query."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finql.eval.metrics import Metrics
from finql.eval.models import EvalResult, EvalRun
from finql.eval.runner import Outcome


@dataclass(frozen=True)
class RunInfo:
    """What ran: everything that can change the numbers."""

    model: str
    prompt_version: str
    few_shot_k: int
    embedding_model: str | None
    git_commit: str | None
    label: str | None


async def save_run(
    sessionmaker: async_sessionmaker[AsyncSession],
    info: RunInfo,
    metrics: Metrics,
    outcomes: Sequence[Outcome],
    *,
    started_at: datetime,
    finished_at: datetime,
) -> int:
    async with sessionmaker() as session, session.begin():
        run = EvalRun(
            started_at=started_at,
            finished_at=finished_at,
            model=info.model,
            prompt_version=info.prompt_version,
            few_shot_k=info.few_shot_k,
            embedding_model=info.embedding_model,
            git_commit=info.git_commit,
            label=info.label,
            question_count=metrics.question_count,
            accuracy=metrics.accuracy,
            valid_sql_rate=metrics.valid_sql_rate,
            refusal_rate=metrics.refusal_rate,
            latency_p50_ms=metrics.latency_p50_ms,
            latency_p95_ms=metrics.latency_p95_ms,
            avg_tokens=metrics.avg_tokens,
            metrics=metrics.as_json(),
        )
        session.add(run)
        await session.flush()
        session.add_all(
            EvalResult(
                run_id=run.id,
                dataset=o.dataset,
                question_id=o.question_id,
                question=o.question,
                scope=o.scope.scope,
                branch_id=o.scope.branch_id,
                passed=o.passed,
                status=o.status,
                reason=o.reason,
                generated_sql=o.generated_sql,
                attempts=o.attempts,
                latency_ms=o.latency_ms,
                input_tokens=o.input_tokens,
                output_tokens=o.output_tokens,
                example_ids=o.example_ids,
            )
            for o in outcomes
        )
        return run.id


async def load_run(
    sessionmaker: async_sessionmaker[AsyncSession], run_id: int
) -> tuple[EvalRun, list[EvalResult]] | None:
    async with sessionmaker() as session:
        run = await session.get(EvalRun, run_id)
        if run is None:
            return None
        results = await session.scalars(
            select(EvalResult)
            .where(EvalResult.run_id == run_id)
            .order_by(EvalResult.dataset.desc(), EvalResult.id)
        )
        return run, list(results)

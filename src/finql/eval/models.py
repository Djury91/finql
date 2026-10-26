from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from finql.core.base_model import Base


class EvalRun(Base):
    """One `finql eval run`: what ran (model, prompt, few-shot) and the headline numbers, so the
    trend across runs is one query away."""

    __tablename__ = "eval_runs"
    __table_args__ = ({"comment": "Eval-futások: modell, promptverzió, few-shot, fő metrikák."},)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    model: Mapped[str] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(Text)
    few_shot_k: Mapped[int] = mapped_column(SmallInteger)
    embedding_model: Mapped[str | None] = mapped_column(Text)
    git_commit: Mapped[str | None] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(Text)
    question_count: Mapped[int] = mapped_column(Integer)
    # Golden set: the generated SQL returns the expected result.
    accuracy: Mapped[float | None] = mapped_column(Float)
    # Golden set: an SQL that passed the validator and ran, right or wrong.
    valid_sql_rate: Mapped[float | None] = mapped_column(Float)
    # Adversarial set: no data came back (declined, rejected, or an empty result).
    refusal_rate: Mapped[float | None] = mapped_column(Float)
    latency_p50_ms: Mapped[int | None]
    latency_p95_ms: Mapped[int | None]
    avg_tokens: Mapped[float | None] = mapped_column(Float)
    # Everything else (per tag, per difficulty, attempts): see eval/metrics.py.
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class EvalResult(Base):
    """One question of one run."""

    __tablename__ = "eval_results"
    __table_args__ = (
        UniqueConstraint("run_id", "dataset", "question_id"),
        {"comment": "Eval-eredmények kérdésenként."},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("app.eval_runs.id", ondelete="CASCADE"))
    dataset: Mapped[str] = mapped_column(Text)
    question_id: Mapped[str] = mapped_column(Text)
    question: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(Text)
    branch_id: Mapped[int | None]
    passed: Mapped[bool]
    # The pipeline's outcome: a query_log status (ok, declined, rejected_validation, …).
    status: Mapped[str] = mapped_column(Text)
    # Why it failed: the result mismatch or the error message.
    reason: Mapped[str | None] = mapped_column(Text)
    generated_sql: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(SmallInteger)
    latency_ms: Mapped[int]
    input_tokens: Mapped[int]
    output_tokens: Mapped[int]
    example_ids: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from finql.core.base_model import Base


class QueryStatus(enum.StrEnum):
    OK = "ok"
    DECLINED = "declined"  # the model wrote no SQL: the question cannot be answered from the data
    REJECTED_VALIDATION = "rejected_validation"  # the SQL broke a validator rule
    REJECTED_COST = "rejected_cost"  # EXPLAIN estimate over the threshold
    REJECTED_BUDGET = "rejected_budget"  # the user's daily token budget is used up
    SQL_ERROR = "sql_error"
    TIMEOUT = "timeout"
    LLM_ERROR = "llm_error"


class QueryLog(Base):
    """Every text-to-SQL attempt, the rejected ones too. Append-only: the application role may
    insert and read, but not change or delete (db/app/010_query_log.sql)."""

    __tablename__ = "query_log"
    # Newest first is a backward scan of these, no DESC needed.
    __table_args__ = (
        CheckConstraint("scope IN ('all', 'branch')", name="scope_valid"),
        CheckConstraint(
            "(scope = 'branch') = (branch_id IS NOT NULL)", name="branch_matches_scope"
        ),
        CheckConstraint("attempt >= 1", name="attempt_positive"),
        # History and the daily token budget: one user's rows.
        Index(None, "user_id", "created_at"),
        # The auditor's list: everyone's rows.
        Index(None, "created_at"),
        {
            "comment": (
                "Text-to-SQL napló: minden kísérlet egy sor, az elutasítottak is. "
                "Csak hozzáfűzhető."
            )
        },
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app.users.id"))
    # The data scope the SQL ran with, as it was at that moment (roles can change later).
    scope: Mapped[str] = mapped_column(Text)
    branch_id: Mapped[int | None]
    question: Mapped[str] = mapped_column(Text)
    # One question may take several attempts (self-repair); each is a row.
    attempt: Mapped[int] = mapped_column(SmallInteger)
    status: Mapped[QueryStatus] = mapped_column(
        Enum(
            QueryStatus,
            name="query_status",
            values_callable=lambda statuses: [status.value for status in statuses],
        )
    )
    generated_sql: Mapped[str | None] = mapped_column(Text)  # as the model wrote it
    executed_sql: Mapped[str | None] = mapped_column(Text)  # regenerated from the AST, with LIMIT
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    explain_cost: Mapped[float | None] = mapped_column(Float)
    row_count: Mapped[int | None]
    duration_ms: Mapped[int | None]  # database time (EXPLAIN + execution)
    model: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    # The few-shot examples (app.sql_examples) the prompt contained. No foreign key: the log is
    # append-only and must not block an example's deletion.
    example_ids: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))
    input_tokens: Mapped[int] = mapped_column(server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(server_default=text("0"))
    llm_latency_ms: Mapped[int | None]
    request_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

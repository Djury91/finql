from typing import Any, Literal

from pydantic import BaseModel, Field

from finql.text_to_sql.service import Answer


class QueryRequest(BaseModel):
    question: str = Field(
        min_length=3, max_length=1000, examples=["Hány 90+ napos késedelmes hitelünk van?"]
    )


class QueryResponse(BaseModel):
    query_id: int  # the query_log row of the final attempt
    status: Literal["ok", "declined"]  # declined: no SQL, `explanation` says why
    sql: str | None  # the SQL that ran (regenerated, with the enforced LIMIT)
    explanation: str
    assumptions: list[str]
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    limit_reached: bool  # the LIMIT cut the result, there may be more rows
    attempts: int  # 1 + self-repair rounds
    duration_ms: int | None  # database time

    @classmethod
    def from_answer(cls, answer: Answer) -> "QueryResponse":
        return cls(
            query_id=answer.query_id,
            status=answer.status,
            sql=answer.sql,
            explanation=answer.explanation,
            assumptions=answer.assumptions,
            columns=answer.columns,
            rows=answer.rows,
            row_count=len(answer.rows),
            limit_reached=answer.limit_reached,
            attempts=answer.attempts,
            duration_ms=answer.duration_ms,
        )

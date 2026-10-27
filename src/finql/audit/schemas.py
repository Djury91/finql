import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from finql.audit.models import QueryStatus


class QueryLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: uuid.UUID
    scope: str
    branch_id: int | None
    question: str
    attempt: int
    status: QueryStatus
    generated_sql: str | None
    executed_sql: str | None
    rejection_reason: str | None
    explain_cost: float | None
    row_count: int | None
    duration_ms: int | None
    model: str | None
    prompt_version: str | None
    input_tokens: int
    output_tokens: int
    llm_latency_ms: int | None
    request_id: str | None
    conversation_id: uuid.UUID | None
    created_at: datetime

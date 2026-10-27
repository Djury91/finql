"""Per-user daily LLM token budget, counted from the records of every LLM call: the query log
(text-to-SQL), the answer log (documents) and the agent's messages."""

import uuid

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from finql.agent.models import Message
from finql.audit.models import QueryLog
from finql.core.errors import AppError
from finql.rag.models import AnswerLog

# The budget resets at midnight in the bank's time zone, not at UTC midnight.
BUDGET_TIME_ZONE = "Europe/Budapest"


class TokenBudgetExceededError(AppError):
    status_code = 429
    code = "token_budget_exceeded"
    message = "Elfogyott a mai keret a nyelvi modell használatára. Holnap újra kérdezhetsz."


async def tokens_used_today(session: AsyncSession, user_id: uuid.UUID) -> int:
    local_midnight = f"date_trunc('day', now() AT TIME ZONE '{BUDGET_TIME_ZONE}')"
    day_start = text(f"{local_midnight} AT TIME ZONE '{BUDGET_TIME_ZONE}'")
    used = 0
    for log in (QueryLog, AnswerLog, Message):
        tokens = await session.scalar(
            select(func.coalesce(func.sum(log.input_tokens + log.output_tokens), 0)).where(
                log.user_id == user_id, log.created_at >= day_start
            )
        )
        used += int(tokens or 0)
    return used


async def check_budget(session: AsyncSession, user_id: uuid.UUID, daily_budget: int) -> int:
    """Raise if the budget is used up; otherwise return the tokens still available.

    Checked before a question, not before every call: a question started within the budget may
    finish its repair rounds, so the overshoot is at most one question. The agent checks before
    each of its model calls, so its overshoot is one model turn and the tools it called.
    """
    remaining = daily_budget - await tokens_used_today(session, user_id)
    if remaining <= 0:
        raise TokenBudgetExceededError()
    return remaining

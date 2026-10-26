import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finql.audit.models import QueryLog, QueryStatus


async def log_query(sessionmaker: async_sessionmaker[AsyncSession], entry: QueryLog) -> int:
    """Write one attempt in its own transaction and commit at once.

    Not in the request's session: a rejected query ends in an error response, which rolls the
    request's transaction back, and the attempt must stay in the log exactly then.
    """
    async with sessionmaker() as session, session.begin():
        session.add(entry)
        await session.flush()
        return entry.id


async def list_queries(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    status: QueryStatus | None = None,
    since: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> Sequence[QueryLog]:
    query = select(QueryLog).order_by(QueryLog.created_at.desc(), QueryLog.id.desc())
    if user_id is not None:
        query = query.where(QueryLog.user_id == user_id)
    if status is not None:
        query = query.where(QueryLog.status == status)
    if since is not None:
        query = query.where(QueryLog.created_at >= since)
    return (await session.scalars(query.limit(limit).offset(offset))).all()

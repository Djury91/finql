import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import select, text
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


# The hash-chained logs (db/app/040_log_chain.sql), by table name.
CHAINED_LOGS = ("query_log", "answer_log")

type ChainProblem = Literal["gap", "link", "content"]


@dataclass(frozen=True)
class ChainStatus:
    log: str
    checked: int  # rows verified from the start, up to the first problem
    broken_at: int | None  # chain_seq of the first problem
    problem: ChainProblem | None  # gap: a row deleted; link: inserted or swapped; content: changed
    head_seq: int | None  # the last verified row: record it elsewhere as an anchor
    head_hash: str | None

    @property
    def intact(self) -> bool:
        return self.problem is None


async def verify_chains(session: AsyncSession) -> list[ChainStatus]:
    """Recompute both log chains in the database. Reads every row: an audit task, not a hot path."""
    statuses = []
    for log in CHAINED_LOGS:
        row = (
            await session.execute(
                text("SELECT * FROM app.verify_log_chain(CAST(:log AS regclass))"),
                {"log": f"app.{log}"},
            )
        ).one()
        statuses.append(ChainStatus(log, *row))
    return statuses


async def anchor_mismatch(session: AsyncSession, log: str, seq: int, row_hash: str) -> str | None:
    """Check a recorded chain head (an anchor) against the log; None if it still holds.

    The chain alone cannot show a rewrite from scratch, or rows cut from its end: the new chain
    is consistent in itself. An anchor kept outside the database can: the row at that position
    must still exist and have the same hash.
    """
    if log not in CHAINED_LOGS:
        raise ValueError(f"not a chained log: {log}")
    stored = await session.scalar(
        text(f"SELECT encode(row_hash, 'hex') FROM app.{log} WHERE chain_seq = :seq"),
        {"seq": seq},
    )
    if stored is None:
        return f"a {seq}. sor hiányzik: a napló végéről sorokat töröltek"
    if stored != row_hash:
        return f"a {seq}. sor hash-e eltér a horgonytól: a láncot újraírták"
    return None

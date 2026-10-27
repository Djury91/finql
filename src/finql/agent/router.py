import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from sqlalchemy import func, select

from finql.agent import service
from finql.agent.models import Conversation, Message
from finql.agent.schemas import ConversationDetail, ConversationOut, MessageOut, MessageRequest
from finql.agent.service import Agent
from finql.auth.dependencies import CurrentUser
from finql.auth.models import UserRole
from finql.core.deps import AppSettings, DbSession
from finql.core.errors import UNAUTHORIZED, AppError, ErrorResponse, NotFoundError
from finql.core.logging import current_request_id
from finql.llm.usage import check_budget
from finql.text_to_sql.service import Pipeline

router = APIRouter(prefix="/chat", tags=["chat"])

NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "Nincs ilyen (saját) beszélgetés"}
}
TURN_ERRORS: dict[int | str, dict[str, Any]] = {
    409: {"model": ErrorResponse, "description": "Ebben a beszélgetésben már készül egy válasz"},
    429: {"model": ErrorResponse, "description": "Elfogyott a napi tokenkeret"},
}


class ConversationBusyError(AppError):
    status_code = 409
    code = "conversation_busy"
    message = "Ebben a beszélgetésben már készül egy válasz. Várd meg, aztán kérdezz újra."


async def own_conversation(
    conversation_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> Conversation:
    conversation = await session.get(Conversation, conversation_id)
    # Someone else's conversation is "not found", not "forbidden": its existence is not told.
    if conversation is None or conversation.user_id != user.id:
        raise NotFoundError("Nincs ilyen beszélgetés.")
    return conversation


async def conversation_for_turn(
    conversation: Annotated[Conversation, Depends(own_conversation)],
    session: DbSession,
    user: CurrentUser,
) -> Conversation:
    """Checked before the stream starts, so these failures are ordinary error responses.

    One turn at a time per conversation: two at once would interleave their messages. The lock
    is the request transaction's, which stays open while the response streams, and is released
    with it, however the stream ends.
    """
    await check_budget(session, user.id, user.daily_token_budget)
    key = int.from_bytes(conversation.id.bytes[:8], "big", signed=True)
    if not await session.scalar(select(func.pg_try_advisory_xact_lock(key))):
        raise ConversationBusyError()
    return conversation


async def get_agent(request: Request, settings: AppSettings) -> Agent:
    state = request.app.state
    pipeline = catalog = None
    if state.llm_engine is not None:  # without it: documents and definitions only
        catalog = await state.catalog_cache.get(state.llm_engine)
        pipeline = Pipeline(
            llm=state.llm_client,
            catalog=catalog,
            llm_engine=state.llm_engine,
            log_sessionmaker=state.sessionmaker,
            settings=settings,
            examples=state.example_selector,
        )
    return Agent(
        model=state.agent_model,
        sessionmaker=state.sessionmaker,
        retriever=state.retriever,
        metrics=state.metrics,
        settings=settings,
        sql_pipeline=pipeline,
        catalog=catalog,
        summarizer=state.summary_client,
    )


@router.post("/conversations", status_code=201, responses=UNAUTHORIZED)
async def create_conversation(session: DbSession, user: CurrentUser) -> ConversationOut:
    """Új beszélgetés az agenttel. A címét az első kérdés adja."""
    conversation = Conversation(user_id=user.id)
    session.add(conversation)
    await session.flush()
    await session.refresh(conversation)
    return ConversationOut.model_validate(conversation)


@router.get("/conversations", responses=UNAUTHORIZED)
async def list_conversations(
    session: DbSession,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ConversationOut]:
    """A saját beszélgetéseim, a legutóbb használt elöl."""
    rows = await session.scalars(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc(), Conversation.id)
        .limit(limit)
        .offset(offset)
    )
    return [ConversationOut.model_validate(row) for row in rows]


@router.get("/conversations/{conversation_id}", responses={**UNAUTHORIZED, **NOT_FOUND})
async def get_conversation(
    conversation_id: uuid.UUID, session: DbSession, user: CurrentUser
) -> ConversationDetail:
    """Egy beszélgetés minden lépése: kérdések, eszközhívások és eredményeik, válaszok.
    A sajátját mindenki látja; az auditor és az admin bárkiét."""
    conversation = await session.get(Conversation, conversation_id)
    may_read = conversation is not None and (
        conversation.user_id == user.id or user.role in (UserRole.AUDITOR, UserRole.ADMIN)
    )
    if conversation is None or not may_read:
        raise NotFoundError("Nincs ilyen beszélgetés.")
    messages = await session.scalars(
        select(Message).where(Message.conversation_id == conversation.id).order_by(Message.id)
    )
    return ConversationDetail(
        **ConversationOut.model_validate(conversation).model_dump(),
        messages=[MessageOut.from_message(message) for message in messages],
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    response_class=EventSourceResponse,
    responses={**UNAUTHORIZED, **NOT_FOUND, **TURN_ERRORS},
)
async def send_message(
    body: MessageRequest,
    user: CurrentUser,
    conversation: Annotated[Conversation, Depends(conversation_for_turn)],
    agent: Annotated[Agent, Depends(get_agent)],
) -> AsyncIterator[ServerSentEvent]:
    """Üzenet az agentnek; a válasz Server-Sent Events stream.

    Események: `turn_start`, `text` (szövegdarab), `tool_start` és `tool_result` (eszközhívás),
    végül `done` (a végleges, ellenőrzött válasz a hivatkozott forrásokkal) vagy `error`. A
    streamelt szöveg hivatkozásait a `done` ellenőrzi: a kliens annak `answer` mezőjét mutassa.
    """
    events = service.run_turn(
        agent, user, conversation.id, body.content, request_id=current_request_id()
    )
    async for event in events:
        yield ServerSentEvent(event=event.type, data=event.data)

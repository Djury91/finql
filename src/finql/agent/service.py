"""The agent: one user message → model turns and tool calls → an answer, streamed as events
(docs/03-architektura.md, 4.).

The loop is ours, not the SDK's tool runner: it runs on any `ChatModel` (a scripted one in the
tests, a demo one without an API key), and every step must be stored, budgeted and turned into
an event as it happens (ADR-009).

Limits per user message: at most `agent_max_tool_calls` tool calls (then the model must answer
from what it has), the daily token budget checked before every model call, and one deadline
for the whole turn. A failing tool is an error result for the model, not the end of the turn.
"""

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finql.agent.memory import (
    Memory,
    MessageSink,
    MessageStore,
    compact,
    load_memory,
    render_history,
)
from finql.agent.metrics import MetricCatalog
from finql.agent.models import MessageRole
from finql.agent.tools import (
    AskDatabase,
    SourceRegistry,
    ToolContext,
    ToolOutput,
    run_tool,
    tools_for,
)
from finql.auth.models import User
from finql.core.config import Settings
from finql.core.errors import AppError
from finql.llm.chat import ChatModel, TextDelta, TurnResult
from finql.llm.client import LLMClient, LLMError
from finql.llm.prompts import load_prompt
from finql.llm.usage import check_budget
from finql.rag.answer import marker_numbers, remove_invalid_markers
from finql.rag.retriever import Retriever
from finql.text_to_sql import service as sql_service
from finql.text_to_sql.schema_context import SchemaCatalog
from finql.text_to_sql.service import Answer, Pipeline

logger = structlog.get_logger(__name__)

PROMPT_VERSION = "agent.v1"

TOOL_LIMIT_REACHED = (
    "Elérted az eszközhívások korlátját ennél a kérdésnél. További eszközt nem hívhatsz: "
    "válaszolj a meglévő eredményekből, és mondd meg, mi maradt nyitva."
)

type EventType = Literal["turn_start", "text", "tool_start", "tool_result", "done", "error"]


@dataclass(frozen=True)
class AgentEvent:
    type: EventType
    data: dict[str, Any]


@dataclass(frozen=True)
class Agent:
    """What a turn needs, assembled per request from the application state."""

    model: ChatModel
    sessionmaker: async_sessionmaker[AsyncSession]  # finql_app: messages, budget
    retriever: Retriever
    metrics: MetricCatalog
    settings: Settings
    sql_pipeline: Pipeline | None = None  # None: text-to-SQL is not configured
    catalog: SchemaCatalog | None = None
    summarizer: LLMClient | None = None  # None: long conversations are cut, not summarized


class TurnError(AppError):
    """The turn ended without an answer (the model was cut off, refused, ran out of time)."""

    status_code = 502
    code = "agent_error"
    message = "Az agent nem tudta befejezni a választ."

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def system_prompt() -> str:
    return load_prompt(PROMPT_VERSION)


async def run_turn(
    agent: Agent,
    user: User,
    conversation_id: uuid.UUID,
    question: str,
    *,
    request_id: str | None = None,
    store: MessageSink | None = None,
    ask_database: AskDatabase | None = None,
) -> AsyncIterator[AgentEvent]:
    """Events: turn_start, then text / tool_start / tool_result as they happen, then done (with
    the checked answer and its sources) or error. Every step is stored as a message.

    The eval passes its own `store` (the messages stay in memory, and the turn starts a new
    conversation) and `ask_database` (no query_log rows): it is not user activity.
    """
    settings = agent.settings
    deadline = asyncio.get_running_loop().time() + settings.agent_timeout_seconds
    if store is None:
        store = MessageStore(agent.sessionmaker, conversation_id, user.id, request_id)
        memory = await load_memory(agent.sessionmaker, conversation_id)
        memory = await compact(
            memory,
            max_turns=settings.agent_history_turns,
            summarizer=agent.summarizer,
            store=store,
        )
    else:
        memory = Memory(None, [])
    ask_database = ask_database or _database_asker(agent, user, conversation_id, request_id)
    messages = render_history(memory, question)
    question_id = await store.add(MessageRole.USER, {"text": question})
    yield AgentEvent(
        "turn_start", {"conversation_id": str(conversation_id), "message_id": question_id}
    )

    tools = tools_for(user, sql_available=ask_database is not None)
    by_name = {tool.name: tool for tool in tools}
    specs = [tool.spec for tool in tools]
    context = ToolContext(
        user=user,
        retriever=agent.retriever,
        metrics=agent.metrics,
        sources=SourceRegistry(),
        ask_database=ask_database,
        catalog=agent.catalog,
    )
    calls_made = 0
    tokens = {"input_tokens": 0, "output_tokens": 0}

    try:
        for step in range(1, settings.agent_max_tool_calls + 3):
            async with agent.sessionmaker() as session:
                await check_budget(session, user.id, user.daily_token_budget)

            turn: TurnResult | None = None
            stream = agent.model.stream_turn(
                system=system_prompt(),
                messages=messages,
                tools=specs,
                allow_tools=calls_made < settings.agent_max_tool_calls,
            )
            async for item in _until(stream, deadline):
                if isinstance(item, TextDelta):
                    if item.text:
                        yield AgentEvent("text", {"delta": item.text, "step": step})
                else:
                    turn = item
            if turn is None:
                raise LLMError("A nyelvi modell válasza hiányos volt.")
            tokens["input_tokens"] += turn.usage.input_tokens
            tokens["output_tokens"] += turn.usage.output_tokens
            messages.append({"role": "assistant", "content": turn.content})
            calls = turn.tool_calls

            if turn.stop_reason == "tool_use" and calls:
                await store.add(
                    MessageRole.ASSISTANT,
                    {"blocks": turn.content, "stop_reason": turn.stop_reason},
                    usage=turn.usage,
                )
                results: list[dict[str, Any]] = []
                for call in calls:
                    yield AgentEvent(
                        "tool_start", {"id": call.id, "name": call.name, "input": call.input}
                    )
                    started = time.perf_counter()
                    tool = by_name.get(call.name)
                    if calls_made >= settings.agent_max_tool_calls:
                        output = ToolOutput(
                            TOOL_LIMIT_REACHED, is_error=True, details={"code": "tool_limit"}
                        )
                    elif tool is None:
                        calls_made += 1  # counts: a model that keeps asking must still stop
                        output = ToolOutput(
                            f"Nincs ilyen eszköz: {call.name}.",
                            is_error=True,
                            details={"code": "unknown_tool"},
                        )
                    else:
                        calls_made += 1
                        async with asyncio.timeout_at(deadline):
                            output = await run_tool(tool, context, call.input)
                    duration_ms = round((time.perf_counter() - started) * 1000)
                    await store.add(
                        MessageRole.TOOL,
                        {
                            "tool_use_id": call.id,
                            "name": call.name,
                            "input": call.input,
                            "is_error": output.is_error,
                            "result": output.content,
                            "details": output.details,
                            "duration_ms": duration_ms,
                        },
                    )
                    yield AgentEvent(
                        "tool_result",
                        {
                            "id": call.id,
                            "name": call.name,
                            "is_error": output.is_error,
                            "duration_ms": duration_ms,
                            "details": output.details,
                        },
                    )
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": call.id,
                            "content": output.content,
                            "is_error": output.is_error,
                        }
                    )
                messages.append({"role": "user", "content": results})
                continue

            if turn.stop_reason == "end_turn" and turn.text.strip():
                answer, citations = check_citations(turn.text, context.sources)
                message_id = await store.add(
                    MessageRole.ASSISTANT,
                    {
                        "blocks": turn.content,
                        "stop_reason": turn.stop_reason,
                        "answer": answer,
                        "citations": [
                            {k: v for k, v in c.items() if k != "content"} for c in citations
                        ],
                        "prompt_version": PROMPT_VERSION,
                    },
                    usage=turn.usage,
                )
                yield AgentEvent(
                    "done",
                    {
                        "message_id": message_id,
                        "answer": answer,
                        "citations": citations,
                        "tool_calls": calls_made,
                        "usage": tokens,
                    },
                )
                return

            await store.add(
                MessageRole.ASSISTANT,
                {"blocks": turn.content, "stop_reason": turn.stop_reason},
                usage=turn.usage,
            )
            raise _unfinished(turn)
        raise TurnError("agent_loop", "Az agent túl sok lépés után sem válaszolt.")
    except TimeoutError:
        error = TurnError("agent_timeout", "Lejárt a válaszra szánt idő.")
    except AppError as exc:  # LLMError, the token budget, TurnError
        error = exc if isinstance(exc, TurnError) else TurnError(exc.code, exc.message)
    logger.warning("agent turn failed", code=error.code, message=error.message)
    await store.add(MessageRole.ASSISTANT, {"error": error.code, "message": error.message})
    yield AgentEvent("error", {"code": error.code, "message": error.message})


def _database_asker(
    agent: Agent, user: User, conversation_id: uuid.UUID, request_id: str | None
) -> AskDatabase | None:
    pipeline = agent.sql_pipeline
    if pipeline is None:
        return None

    async def ask(question: str) -> Answer:
        async with agent.sessionmaker() as session:
            return await sql_service.answer_question(
                pipeline,
                session,
                user,
                question,
                request_id=request_id,
                conversation_id=conversation_id,
            )

    return ask


def check_citations(text: str, sources: SourceRegistry) -> tuple[str, list[dict[str, Any]]]:
    """The answer without the markers that point to no source, and the cited sources. The
    numbers were streamed as they came; the final answer in the done event is the checked one."""
    count = len(sources.hits)
    cited = [n for n in marker_numbers(text) if 1 <= n <= count]
    citations = []
    for number in sorted(cited):
        hit = sources.hits[number - 1]
        citations.append(
            {
                "number": number,
                "ref": hit.ref,
                "source_path": hit.source_path,
                "title": hit.title,
                "section": hit.section,
                "effective_from": hit.effective_from.isoformat(),
                "content": hit.content,
            }
        )
    return remove_invalid_markers(text, count).strip(), citations


def _unfinished(turn: TurnResult) -> TurnError:
    if turn.stop_reason == "refusal":
        return TurnError("llm_refused", "A nyelvi modell ezt a kérést nem teljesítette.")
    if turn.stop_reason == "max_tokens":
        return TurnError("llm_incomplete", "A nyelvi modell válasza túl hosszú lett, megszakadt.")
    return TurnError("llm_incomplete", "A nyelvi modell nem adott választ.")


async def _until[T](stream: AsyncIterator[T], deadline: float) -> AsyncIterator[T]:
    """The stream's items, each awaited within the deadline. The timeout never spans a yield:
    the time the client takes to read an event is not the model's."""
    try:
        while True:
            async with asyncio.timeout_at(deadline):
                try:
                    item = await anext(stream)
                except StopAsyncIteration:
                    return
            yield item
    finally:
        aclose = getattr(stream, "aclose", None)
        if aclose is not None:  # the provider's stream (an HTTP response) is closed at once
            await aclose()

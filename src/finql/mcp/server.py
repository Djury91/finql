"""The MCP server (phase 8, ADR-013): the agent's tools for an MCP client such as Claude Desktop.

The client's model asks; the tools run here, with one FinQL user's rights, the same way they run
for the agent and the API: the data scope and the reading level come from the user record, every
data question goes through the text-to-SQL chain (validator, cost guard, read-only role, RLS) and
into the query log, and the daily token budget applies. The client gets no SQL access and no
document the user could not read.

The user is fixed when the server starts (`finql mcp`, with FINQL_MCP_EMAIL and
FINQL_MCP_PASSWORD), and re-read before every request: a deactivated user or a changed role
takes effect at once, not at the next start.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import mcp_types as types
import structlog
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server
from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from finql import __version__
from finql.agent.metrics import MetricCatalog, load_metrics
from finql.agent.tools import (
    AskDatabase,
    SourceRegistry,
    Tool,
    ToolContext,
    run_tool,
    tools_for,
)
from finql.auth.models import User
from finql.auth.service import authenticate
from finql.core.config import Settings
from finql.core.db import create_engine, create_sessionmaker
from finql.core.errors import NotAuthenticatedError
from finql.core.logging import configure_logging
from finql.core.telemetry import configure_telemetry, shutdown_telemetry
from finql.llm.anthropic_client import AnthropicClient
from finql.llm.client import LLMClient
from finql.llm.embeddings import Embedder, VoyageEmbedder, build_embedder
from finql.rag.retriever import Retriever
from finql.text_to_sql import service as sql_service
from finql.text_to_sql.examples import ExampleSelector, build_example_selector
from finql.text_to_sql.schema_context import CatalogCache

logger = structlog.get_logger(__name__)

INSTRUCTIONS = (
    "FinQL: egy bank adatai és belső szabályzatai, a bejelentkezett felhasználó jogaival. "
    "Számadathoz a query_database eszközt hívd egy magyar nyelvű kérdéssel (nem SQL-lel): a "
    "szerver ellenőrzött lekérdezést készít belőle, és megmondja, milyen adatkörre futott. "
    "Szabályhoz, díjhoz, teendőhöz a search_documents kell; a találatok számozott források, a "
    "válaszban ezekre hivatkozz [n] alakban. Fogalom definíciójához a get_metric_definition."
)

# The tools read data; they write only the audit log. No tool reaches outside the bank's data.
READ_ONLY = types.ToolAnnotations(
    read_only_hint=True, destructive_hint=False, open_world_hint=False
)


@dataclass(frozen=True)
class Backend:
    """What the tools need, built once per server process. The same parts as the API's lifespan
    (main.create_app), without the chat agent: the client brings its own model."""

    settings: Settings
    sessionmaker: async_sessionmaker[AsyncSession]  # finql_app: users, logs, documents
    llm_engine: AsyncEngine | None  # finql_llm_reader: runs the generated SQL
    llm_client: LLMClient  # text-to-SQL
    catalog_cache: CatalogCache
    retriever: Retriever
    metrics: MetricCatalog
    examples: ExampleSelector | None


@asynccontextmanager
async def open_backend(
    settings: Settings, *, llm_client: LLMClient | None = None, embedder: Embedder | None = None
) -> AsyncIterator[Backend]:
    """`llm_client`, `embedder`: tests pass fakes; otherwise they follow the settings."""
    from finql.main import build_llm_clients  # the API module, only for its client choice

    app_engine = create_engine(settings.database_url.get_secret_value())
    llm_engine = (
        create_engine(settings.llm_database_url.get_secret_value())
        if settings.llm_database_url
        else None
    )
    sql_client = llm_client or build_llm_clients(settings).sql
    embedder = embedder or build_embedder(settings)
    sessionmaker = create_sessionmaker(app_engine)
    try:
        yield Backend(
            settings=settings,
            sessionmaker=sessionmaker,
            llm_engine=llm_engine,
            llm_client=sql_client,
            catalog_cache=CatalogCache(),
            retriever=Retriever(sessionmaker, embedder),
            metrics=load_metrics(),
            examples=build_example_selector(settings, sessionmaker, embedder),
        )
    finally:
        if isinstance(sql_client, AnthropicClient):
            await sql_client.close()
        if isinstance(embedder, VoyageEmbedder):
            await embedder.close()
        await app_engine.dispose()
        if llm_engine is not None:
            await llm_engine.dispose()


async def login(backend: Backend, email: str, password: str) -> uuid.UUID:
    """The same check as POST /auth/token: an unknown user, a wrong password and an inactive
    account fail alike."""
    async with backend.sessionmaker() as session, session.begin():
        user = await authenticate(session, email, password)
        return user.id


def build_server(backend: Backend, user_id: uuid.UUID) -> Server[Any]:
    # One numbering for the whole session: a document part keeps its number across calls, so
    # the client's model can cite the sources of several searches in one answer.
    sources = SourceRegistry()

    async def current_user() -> User:
        async with backend.sessionmaker() as session:
            user = await session.get(User, user_id)
        if user is None or not user.is_active:
            raise NotAuthenticatedError("A felhasználó le van tiltva, vagy nem létezik.")
        return user

    async def offered_tools(user: User) -> list[Tool]:
        return tools_for(user, sql_available=backend.llm_engine is not None)

    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        user = await current_user()
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=tool.name,
                    description=tool.description,
                    input_schema=tool.input_type.model_json_schema(),
                    annotations=READ_ONLY,
                )
                for tool in await offered_tools(user)
            ]
        )

    async def call_tool(
        ctx: ServerRequestContext[Any], params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        request_id = f"mcp-{uuid.uuid4().hex}"  # in the query log: this call came over MCP
        structlog.contextvars.bind_contextvars(request_id=request_id)
        # The SDK already opens the call's server span ("tools/call <tool>", with the MCP
        # attributes and the client's trace context, if it sent one): ours only adds the id that
        # leads to the query log.
        trace.get_current_span().set_attribute("finql.request_id", request_id)
        try:
            return await answer(params, request_id)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")

    async def answer(params: types.CallToolRequestParams, request_id: str) -> types.CallToolResult:
        try:
            user = await current_user()
        except NotAuthenticatedError as exc:
            return _error(exc.message)
        # Only what the user is offered can be called: an auditor has no data tool.
        tool = next((t for t in await offered_tools(user) if t.name == params.name), None)
        if tool is None:
            return _error(
                f"Nincs ilyen eszköz, vagy ennek a felhasználónak nem elérhető: {params.name}"
            )
        context = ToolContext(
            user=user,
            retriever=backend.retriever,
            metrics=backend.metrics,
            sources=sources,
            ask_database=await _database_asker(backend, user, request_id),
            catalog=(
                await backend.catalog_cache.get(backend.llm_engine)
                if backend.llm_engine is not None
                else None
            ),
        )
        output = await run_tool(tool, context, params.arguments or {})
        logger.info("mcp tool call", tool=tool.name, user_id=str(user.id), error=output.is_error)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=output.content)],
            is_error=output.is_error,
        )

    return Server(
        "finql",
        version=__version__,
        title="FinQL",
        instructions=INSTRUCTIONS,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )


async def _database_asker(backend: Backend, user: User, request_id: str) -> AskDatabase | None:
    if backend.llm_engine is None:
        return None
    pipeline = sql_service.Pipeline(
        llm=backend.llm_client,
        catalog=await backend.catalog_cache.get(backend.llm_engine),
        llm_engine=backend.llm_engine,
        log_sessionmaker=backend.sessionmaker,
        settings=backend.settings,
        examples=backend.examples,
    )

    async def ask(question: str) -> sql_service.Answer:
        async with backend.sessionmaker() as session:
            return await sql_service.answer_question(
                pipeline, session, user, question, request_id=request_id
            )

    return ask


def _error(message: str) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=message)], is_error=True
    )


async def serve_stdio(settings: Settings) -> None:
    """`finql mcp`: log in, then serve one client over stdin/stdout until it disconnects.

    stdout is the protocol's channel: the logs go to stderr (core/logging.py), and while the
    server runs the SDK points file descriptor 1 at stderr as well.
    """
    # First of all: every log line to stderr. Unconfigured, structlog prints to stdout, and a
    # line logged before the SDK takes over stdout would land in the protocol stream.
    configure_logging(settings.log_level, json_logs=True)
    if settings.mcp_email is None or settings.mcp_password is None:
        raise NotAuthenticatedError("Hiányzik a FINQL_MCP_EMAIL vagy a FINQL_MCP_PASSWORD.")
    configure_telemetry(settings)  # before the engines: they are traced only if created after
    try:
        await _serve(settings)
    finally:
        shutdown_telemetry()


async def _serve(settings: Settings) -> None:
    assert settings.mcp_email is not None and settings.mcp_password is not None
    async with open_backend(settings) as backend:
        user_id = await login(backend, settings.mcp_email, settings.mcp_password.get_secret_value())
        server = build_server(backend, user_id)
        logger.info("mcp server ready", user_id=str(user_id))
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import structlog
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from finql import __version__, health
from finql.agent.demo import DemoSummaryClient, demo_agent_model
from finql.agent.metrics import load_metrics
from finql.agent.router import router as agent_router
from finql.audit.router import router as audit_router
from finql.auth.router import router as auth_router
from finql.core.config import Settings, get_settings
from finql.core.db import create_engine, create_sessionmaker
from finql.core.errors import install_error_handlers
from finql.core.logging import RequestContextMiddleware, configure_logging
from finql.core.telemetry import EXCLUDED_URLS, configure_telemetry, shutdown_telemetry
from finql.llm.anthropic_client import AnthropicClient
from finql.llm.chat import ChatModel
from finql.llm.client import LLMClient
from finql.llm.embeddings import Embedder, VoyageEmbedder, build_embedder
from finql.rag.demo import ExtractiveDemoClient
from finql.rag.retriever import Retriever
from finql.rag.router import router as rag_router
from finql.text_to_sql.demo import demo_llm_client
from finql.text_to_sql.examples import build_example_selector
from finql.text_to_sql.router import router as text_to_sql_router
from finql.text_to_sql.schema_context import CatalogCache
from finql.web.router import STATIC_DIR
from finql.web.router import router as web_router
from finql.web.scenarios import router as scenarios_router

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class LLMClients:
    sql: LLMClient  # text-to-SQL
    rag: LLMClient  # document answers
    agent: ChatModel  # the chat agent's turns
    summary: LLMClient  # conversation summaries (the cheap model)


def build_llm_clients(settings: Settings) -> LLMClients:
    """One Anthropic client serves SQL, documents and the agent; the summary has its own (Haiku,
    low effort, no refusal fallback: there is none for Haiku). Without an API key each gets its
    own stand-in."""
    if settings.llm_provider == "fake":
        return LLMClients(
            demo_llm_client(), ExtractiveDemoClient(), demo_agent_model(), DemoSummaryClient()
        )
    client = AnthropicClient(settings)
    summary = AnthropicClient(
        settings, model=settings.summary_model, effort="low", refusal_fallback=False
    )
    return LLMClients(client, client, client, summary)


def create_app(
    settings: Settings | None = None,
    *,
    llm_client: LLMClient | None = None,
    chat_model: ChatModel | None = None,
    summary_client: LLMClient | None = None,
    embedder: Embedder | None = None,
) -> FastAPI:
    """`llm_client`, `chat_model`, `summary_client`, `embedder`: tests pass fakes; otherwise
    they follow the settings (FINQL_LLM_PROVIDER, FINQL_EMBEDDING_PROVIDER)."""
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_logs=settings.json_logs)
    # Before the lifespan creates the engines: they are traced only if created afterwards.
    tracing = configure_telemetry(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Two pools, two database roles: the application (finql_app: the app schema only) and the
        # LLM-generated SQL (finql_llm_reader: read-only, analytics views only).
        app.state.app_engine = create_engine(settings.database_url.get_secret_value())
        app.state.sessionmaker = create_sessionmaker(app.state.app_engine)
        app.state.llm_engine = (
            create_engine(settings.llm_database_url.get_secret_value())
            if settings.llm_database_url
            else None
        )
        app.state.catalog_cache = CatalogCache()
        clients = build_llm_clients(settings)
        app.state.llm_client = llm_client or clients.sql
        app.state.rag_llm_client = llm_client or clients.rag
        app.state.agent_model = chat_model or clients.agent
        app.state.summary_client = summary_client or clients.summary
        app.state.metrics = load_metrics()
        app.state.embedder = embedder or build_embedder(settings)
        # Without an embedder the document search runs on full text only.
        app.state.retriever = Retriever(app.state.sessionmaker, app.state.embedder)
        app.state.example_selector = build_example_selector(
            settings, app.state.sessionmaker, app.state.embedder
        )
        if app.state.example_selector is None and settings.few_shot_k > 0:
            logger.warning("dynamic few-shot is off: no embedder (FINQL_VOYAGE_API_KEY)")
        if app.state.embedder is None:
            logger.warning("document search runs on full text only: no embedder")
        try:
            yield
        finally:
            for client in {id(c): c for c in (clients.sql, clients.summary)}.values():
                if isinstance(client, AnthropicClient):
                    await client.close()
            if isinstance(app.state.embedder, VoyageEmbedder):
                await app.state.embedder.close()
            await app.state.app_engine.dispose()
            if app.state.llm_engine is not None:
                await app.state.llm_engine.dispose()
            shutdown_telemetry()

    app = FastAPI(title="FinQL", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(auth_router)
    app.include_router(text_to_sql_router)
    app.include_router(rag_router)
    app.include_router(agent_router)
    app.include_router(audit_router)
    app.include_router(web_router)
    app.include_router(scenarios_router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    if tracing:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        # The server span of every request: the root the model calls, tools and queries hang on.
        # Without the ASGI send/receive spans: a streamed answer would add one per chunk.
        FastAPIInstrumentor.instrument_app(
            app, excluded_urls=EXCLUDED_URLS, exclude_spans=["send", "receive"]
        )
    return app

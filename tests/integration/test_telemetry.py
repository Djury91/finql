"""Tracing end to end (core/telemetry.py, ADR-014): one trace per request, nested as the work
nests, linked to the audit log, and without bank data in it.

The tracer provider is global and can be set once per process: this module sets an in-memory
one, and stops it when done, so the later modules export nothing.
"""

import asyncio
from collections.abc import Iterator
from typing import Any

import anthropic
import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient
from mcp import Client
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode
from pydantic import BaseModel

from finql.auth.admin import DEMO_USERS, create_users
from finql.core.db import async_url
from finql.core.telemetry import configure_telemetry, tracer
from finql.llm.anthropic_client import AnthropicClient, sdk_client
from finql.llm.embeddings import HashingEmbedder
from finql.llm.fake_chat import FakeChatModel, Turn
from finql.llm.fake_client import FakeLLMClient
from finql.main import create_app
from finql.mcp.server import build_server, login, open_backend
from tests.helpers import make_settings
from tests.unit.llm.test_anthropic_client import message

from .api import ANALYST, PASSWORD, PECS_MANAGER, bearer
from .api import login as api_login
from .db import DbUrls
from .test_agent import ask, of

pytestmark = pytest.mark.integration

EXPORTER = InMemorySpanExporter()
ACCOUNTS_SQL = "SELECT branch_id, count(*) AS accounts FROM accounts GROUP BY branch_id"
# Text that must never reach a span: the question carries it, the trace must not.
SECRET = "Kovács Titkos Ügyfél"
FAKE = FakeLLMClient(
    rules={
        # Longer key first: the first rule whose key occurs in the prompt wins.
        "#otel-bad": {"sql": "DELETE FROM accounts", "explanation": "", "assumptions": []},
        "#otel": {"sql": ACCOUNTS_SQL, "explanation": "Teszt.", "assumptions": []},
    }
)
CHAT = FakeChatModel(
    rules={
        "#otel-agent": [
            Turn(tool_calls=[("query_database", {"question": f"Számlák {SECRET} #otel"})]),
            Turn(text="Kész."),
        ]
    }
)


class Out(BaseModel):
    a: int


def settings_for(urls: DbUrls) -> Any:
    return make_settings(
        async_url(urls.app),
        llm_database_url=async_url(urls.llm_reader),
        demo_password=PASSWORD,
        embedding_provider="hashing",
        otel_service_name="finql-test",
    )


@pytest.fixture(scope="module", autouse=True)
def tracing(seeded_db: DbUrls) -> Iterator[None]:
    asyncio.run(create_users(seeded_db.migrator, list(DEMO_USERS), PASSWORD))
    assert configure_telemetry(settings_for(seeded_db), exporter=EXPORTER)
    yield
    EXPORTER.shutdown()  # later modules: spans are dropped, not kept in memory


@pytest.fixture(autouse=True)
def fresh_spans() -> None:
    EXPORTER.clear()


@pytest.fixture(scope="module")
def client(seeded_db: DbUrls, tracing: None) -> Iterator[TestClient]:
    app = create_app(
        settings_for(seeded_db), llm_client=FAKE, chat_model=CHAT, embedder=HashingEmbedder()
    )
    with TestClient(app) as test_client:
        yield test_client


def spans() -> list[ReadableSpan]:
    return list(EXPORTER.get_finished_spans())


def named(name: str) -> ReadableSpan:
    matches = [s for s in spans() if s.name == name]
    assert len(matches) == 1, [s.name for s in spans()]
    return matches[0]


def parent_of(span: ReadableSpan) -> ReadableSpan:
    assert span.parent is not None, span.name
    return next(s for s in spans() if s.context.span_id == span.parent.span_id)


def attrs(item: Any) -> dict[str, Any]:
    """A span's or an event's attributes (the SDK types them as optional)."""
    return dict(item.attributes or {})


def assert_no_bank_data(text: str) -> None:
    for span in spans():
        values = [*attrs(span).values()] + [
            v for event in span.events for v in attrs(event).values()
        ]
        assert not any(text in str(value) for value in values), span.name


def test_a_data_question_is_one_trace_linked_to_the_audit_log(client: TestClient) -> None:
    headers = bearer(api_login(client, PECS_MANAGER))
    EXPORTER.clear()  # the login's spans

    response = client.post("/query", headers=headers, json={"question": f"{SECRET} #otel"})

    assert response.status_code == 200, response.text
    pipeline = named("text_to_sql")
    assert parent_of(pipeline).kind is SpanKind.SERVER  # the API request's span
    assert parent_of(named("validate_sql")) == pipeline
    execute = named("execute_sql")
    assert parent_of(execute) == pipeline
    # The cost guard's EXPLAIN and the query, as database spans under execute_sql.
    database = [s for s in spans() if s.parent and s.parent.span_id == execute.context.span_id]
    assert len(database) >= 2 and all(s.kind is SpanKind.CLIENT for s in database)
    assert {s.context.trace_id for s in spans()} == {pipeline.context.trace_id}

    # The link to the audit log: the query_log id of the attempt, and the data scope.
    (logged,) = [e for e in pipeline.events if e.name == "query_log"]
    assert attrs(logged)["finql.query_id"] == response.json()["query_id"]
    assert attrs(pipeline)["finql.data_scope"] == "branch"
    assert attrs(pipeline)["finql.status"] == "ok"
    assert_no_bank_data(SECRET)


def test_a_rejected_query_marks_its_spans_failed(client: TestClient) -> None:
    headers = bearer(api_login(client, ANALYST))
    EXPORTER.clear()

    response = client.post("/query", headers=headers, json={"question": "Törlés #otel-bad"})

    assert response.status_code == 422
    assert named("validate_sql").status.status_code is StatusCode.ERROR
    pipeline = named("text_to_sql")
    assert pipeline.status.status_code is StatusCode.ERROR
    (logged,) = [e for e in pipeline.events if e.name == "query_log"]
    assert attrs(logged)["finql.status"] == "rejected_validation"


def test_an_agent_turn_nests_its_tools_and_queries(client: TestClient) -> None:
    headers = bearer(api_login(client, ANALYST))
    EXPORTER.clear()

    _, events = ask(client, headers, "Hány számla van? #otel-agent")

    assert of(events, "done"), events
    turn = named("invoke_agent finql")
    tool = named("execute_tool query_database")
    assert parent_of(tool) == turn
    assert parent_of(named("text_to_sql")) == tool
    assert attrs(turn)["gen_ai.operation.name"] == "invoke_agent"
    assert attrs(turn)["finql.tool_calls"] == 1
    # One span per streamed chunk would bury the work: the ASGI send/receive spans are off.
    assert not [s for s in spans() if s.name.endswith((" http send", " http receive"))]
    assert_no_bank_data(SECRET)


async def test_an_mcp_call_is_a_trace_of_its_own(seeded_db: DbUrls) -> None:
    async with open_backend(settings_for(seeded_db), llm_client=FAKE) as backend:
        user_id = await login(backend, ANALYST, PASSWORD)
        async with Client(build_server(backend, user_id)) as client:
            EXPORTER.clear()
            result = await client.call_tool("query_database", {"question": f"{SECRET} #otel"})

    assert not result.is_error
    # The SDK's server span is the root; we add the id that leads to the query log.
    root = named("tools/call query_database")
    assert root.parent is None and root.kind is SpanKind.SERVER
    assert attrs(root)["mcp.method.name"] == "tools/call"
    assert str(attrs(root)["finql.request_id"]).startswith("mcp-")
    assert parent_of(named("execute_tool query_database")) == root
    assert_no_bank_data(SECRET)


async def test_model_calls_are_traced_by_the_sdk_without_their_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Even if the environment asks the SDK for content, our client keeps it out (SDK_TELEMETRY).
    monkeypatch.setenv("ANTHROPIC_OPEN_TELEMETRY_TRACES_CONTENT_MODE", "content")
    sdk = sdk_client(
        make_settings("postgresql+asyncpg://u:p@127.0.0.1:1/x", anthropic_api_key="test-key"),
        max_retries=0,
        http_client=anthropic.DefaultAsyncHttpxClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=message('{"a": 1}')))
        ),
    )
    model = AnthropicClient(make_settings("postgresql+asyncpg://u:p@127.0.0.1:1/x"), client=sdk)

    with tracer.start_as_current_span("kérés"):
        await model.generate_structured(system="Rendszer.", prompt=SECRET, output_type=Out)

    (call,) = [s for s in spans() if s.name == "anthropic.messages.create"]
    assert parent_of(call).name == "kérés"  # under whatever span was current
    assert attrs(call)["gen_ai.usage.input_tokens"] > 0
    assert attrs(call)["gen_ai.usage.cache_read.input_tokens"] == 4000
    assert not [key for key in attrs(call) if "message" in key and "stop_reason" not in key]
    assert_no_bank_data(SECRET)

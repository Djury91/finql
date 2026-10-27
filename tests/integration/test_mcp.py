"""The MCP server (finql/mcp/server.py): the agent's tools over MCP, with one user's rights.

Most tests connect an MCP client to the server in-process; one starts `finql mcp` as a real
subprocess over stdio, the way Claude Desktop does.
"""

import asyncio
import json
import re
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import psycopg
import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from finql.auth.admin import DEMO_USERS, NewUser, create_users
from finql.auth.models import UserRole
from finql.core.db import async_url
from finql.core.errors import NotAuthenticatedError
from finql.llm.embeddings import HashingEmbedder
from finql.llm.fake_client import FakeLLMClient
from finql.mcp.server import build_server, login, open_backend
from tests.helpers import TEST_JWT_SECRET, make_settings

from .api import ANALYST, AUDITOR, PASSWORD, PECS_MANAGER
from .db import DbUrls
from .test_rag import DOCUMENTS, ingest
from .test_security import as_owner, branch_id

pytestmark = pytest.mark.integration

DISABLED_LATER = "mcp-tiltott@minta-bank.example"
ACCOUNTS_BY_BRANCH = "SELECT branch_id, count(*) AS accounts FROM accounts GROUP BY branch_id"
FAKE = FakeLLMClient(
    rules={"#mcp-accounts": {"sql": ACCOUNTS_BY_BRANCH, "explanation": "Teszt.", "assumptions": []}}
)


@pytest.fixture(scope="module", autouse=True)
def users_and_documents(seeded_db: DbUrls) -> None:
    users = [*DEMO_USERS, NewUser(DISABLED_LATER, "Később Tiltott", UserRole.ANALYST)]
    asyncio.run(create_users(seeded_db.migrator, users, PASSWORD))
    asyncio.run(ingest(seeded_db, DOCUMENTS))


def settings_for(urls: DbUrls, **overrides: Any) -> Any:
    return make_settings(
        async_url(urls.app),
        llm_database_url=async_url(urls.llm_reader),
        embedding_provider="hashing",
        **overrides,
    )


@asynccontextmanager
async def mcp_client(urls: DbUrls, email: str) -> AsyncIterator[Client]:
    async with open_backend(
        settings_for(urls), llm_client=FAKE, embedder=HashingEmbedder()
    ) as backend:
        user_id = await login(backend, email, PASSWORD)
        async with Client(build_server(backend, user_id)) as client:
            yield client


def text_of(result: Any) -> str:
    return "\n".join(part.text for part in result.content)


async def test_the_tools_follow_the_users_role(seeded_db: DbUrls) -> None:
    async with mcp_client(seeded_db, ANALYST) as analyst:
        analyst_tools = (await analyst.list_tools()).tools
        instructions = analyst.instructions
    async with mcp_client(seeded_db, AUDITOR) as auditor:
        auditor_tools = (await auditor.list_tools()).tools

    assert {t.name for t in analyst_tools} == {
        "query_database",
        "describe_schema",
        "search_documents",
        "get_metric_definition",
    }
    # An auditor has no bank data: no data tool is offered.
    assert {t.name for t in auditor_tools} == {"search_documents", "get_metric_definition"}
    assert all(t.annotations and t.annotations.read_only_hint for t in analyst_tools)
    query = next(t for t in analyst_tools if t.name == "query_database")
    assert query.input_schema["required"] == ["question"]
    assert instructions and "query_database" in instructions


async def test_a_data_question_runs_with_the_users_scope_and_is_logged(seeded_db: DbUrls) -> None:
    async with mcp_client(seeded_db, PECS_MANAGER) as client:
        result = await client.call_tool(
            "query_database", {"question": "Számlák fiókonként #mcp-accounts"}
        )

    assert not result.is_error, text_of(result)
    body = json.loads(text_of(result))
    pecs = branch_id(seeded_db, "PEC01")
    # The same SQL would list every branch for an analyst; RLS keeps the manager's own.
    assert [row[0] for row in body["rows"]] == [pecs]
    assert f"branch_id = {pecs}" in body["data_scope"]
    ((logged,),) = as_owner(
        seeded_db,
        "SELECT count(*) FROM app.query_log l JOIN app.users u ON u.id = l.user_id "
        f"WHERE u.email = '{PECS_MANAGER}' AND l.request_id LIKE 'mcp-%' "
        "AND l.question LIKE '%#mcp-accounts'",
    )
    assert logged >= 1


async def test_a_tool_not_offered_to_the_user_cannot_be_called(seeded_db: DbUrls) -> None:
    async with mcp_client(seeded_db, AUDITOR) as client:
        result = await client.call_tool(
            "query_database", {"question": "Hány ügyfél van? #mcp-auditor"}
        )

    assert result.is_error
    ((logged,),) = as_owner(
        seeded_db, "SELECT count(*) FROM app.query_log WHERE question LIKE '%#mcp-auditor'"
    )
    assert logged == 0  # refused before the text-to-SQL chain, nothing to log


async def test_invalid_input_is_an_error_result_for_the_model(seeded_db: DbUrls) -> None:
    async with mcp_client(seeded_db, ANALYST) as client:
        result = await client.call_tool("query_database", {"question": "x", "sql": "DROP TABLE x"})

    assert result.is_error
    assert "Hibás bemenet" in text_of(result)


async def test_a_deactivated_user_is_refused_at_once(seeded_db: DbUrls) -> None:
    async with mcp_client(seeded_db, DISABLED_LATER) as client:
        before = await client.call_tool("get_metric_definition", {"name": "NPL"})
        set_active(seeded_db, DISABLED_LATER, active=False)
        try:
            after = await client.call_tool("get_metric_definition", {"name": "NPL"})
        finally:
            set_active(seeded_db, DISABLED_LATER, active=True)

    assert not before.is_error
    assert after.is_error and "le van tiltva" in text_of(after)


async def test_source_numbers_hold_for_the_whole_session(seeded_db: DbUrls) -> None:
    async with mcp_client(seeded_db, ANALYST) as client:
        first = await client.call_tool("search_documents", {"query": "késedelmi kamat", "top_k": 3})
        other = await client.call_tool("search_documents", {"query": "panaszkezelés határideje"})
        again = await client.call_tool("search_documents", {"query": "késedelmi kamat", "top_k": 3})

    assert not first.is_error and not other.is_error
    assert text_of(again) == text_of(first)  # the same parts keep their numbers
    # A number names one part for the whole session: a number seen before is the same part.
    seen = sources_by_number(text_of(first))
    for number, block in sources_by_number(text_of(other)).items():
        assert seen.get(number, block) == block
    assert set(seen) == {1, 2, 3}


def sources_by_number(text: str) -> dict[int, str]:
    blocks = re.findall(r'<source id="(\d+)"(.*?)</source>', text, re.S)
    return {int(number): block for number, block in blocks}


async def test_the_login_fails_alike_for_a_wrong_password_and_an_unknown_user(
    seeded_db: DbUrls,
) -> None:
    async with open_backend(settings_for(seeded_db), llm_client=FAKE) as backend:
        for email, password in ((ANALYST, "rossz-jelszo"), ("nincs@minta-bank.example", PASSWORD)):
            with pytest.raises(NotAuthenticatedError) as caught:
                await login(backend, email, password)
            assert caught.value.message == "Hibás e-mail-cím vagy jelszó."


async def test_finql_mcp_serves_over_stdio(seeded_db: DbUrls, tmp_path: Path) -> None:
    # A real subprocess, started from an unrelated directory (no .env there), like an MCP
    # client starts it. If anything wrote to stdout besides the protocol, the session would break.
    env = {
        "FINQL_ENV": "test",
        "FINQL_DATABASE_URL": async_url(seeded_db.app),
        "FINQL_LLM_DATABASE_URL": async_url(seeded_db.llm_reader),
        "FINQL_JWT_SECRET": TEST_JWT_SECRET,
        "FINQL_LLM_PROVIDER": "fake",
        "FINQL_EMBEDDING_PROVIDER": "hashing",
        "FINQL_MCP_EMAIL": ANALYST,
        "FINQL_MCP_PASSWORD": PASSWORD,
    }
    server = StdioServerParameters(
        command=sys.executable,
        args=["-c", "from finql.cli import app; app()", "mcp"],
        env=env,
        cwd=tmp_path,
    )
    async with Client(server, read_timeout_seconds=60) as client:
        tools = {t.name for t in (await client.list_tools()).tools}
        result = await client.call_tool("get_metric_definition", {"name": "NPL-ráta"})

    assert "query_database" in tools
    assert not result.is_error and "Definíció" in text_of(result)


def set_active(urls: DbUrls, email: str, *, active: bool) -> None:
    with psycopg.connect(urls.conninfo("migrator")) as conn:
        conn.execute("SET ROLE finql_owner")
        conn.execute("UPDATE app.users SET is_active = %s WHERE email = %s", [active, email])

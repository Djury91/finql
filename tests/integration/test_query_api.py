"""The text-to-SQL pipeline end to end: real database, scripted LLM (FakeLLMClient).

Every question carries a tag (#…) that picks its scripted answer, so the tests share one app.
"""

import asyncio
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from finql.auth.admin import DEMO_USERS, NewUser, create_users
from finql.auth.models import UserRole
from finql.core.db import async_url
from finql.llm.client import LLMError
from finql.llm.fake_client import FakeLLMClient
from finql.main import create_app
from finql.text_to_sql.demo import EXAMPLE_QUESTIONS
from tests.helpers import make_settings

from .api import ADMIN, ANALYST, AUDITOR, PASSWORD, PECS_MANAGER, bearer, login
from .db import DbUrls
from .test_security import as_owner, as_reader, branch_id

pytestmark = pytest.mark.integration

BUDGET_USER = "keret@minta-bank.example"
NINETY_PLUS = EXAMPLE_QUESTIONS["Hány 90+ napos késedelmes hitelünk van?"]


def sql(query: str, explanation: str = "Teszt.") -> dict[str, Any]:
    return {"sql": query, "explanation": explanation, "assumptions": []}


FAKE = FakeLLMClient(
    rules={
        "#example": sql(NINETY_PLUS),
        "#accounts-by-branch": sql(
            "SELECT branch_id, count(*) AS accounts FROM accounts GROUP BY branch_id"
        ),
        "#delete": sql("DELETE FROM transactions"),
        "#set-config": sql("SELECT set_config('app.scope', 'all', true), count(*) FROM customers"),
        "#pii": sql("SELECT full_name, tax_id FROM bank.customers"),
        "#repair-column": [
            sql("SELECT count(*) FROM loans WHERE days_late > 90"),
            sql(NINETY_PLUS),
        ],
        "#repair-view": [sql("SELECT count(*) FROM loan"), sql(NINETY_PLUS)],
        "#never-right": sql("SELECT no_such_column FROM loans"),
        "#cross-join": sql("SELECT count(*) FROM transactions a, transactions b"),
        "#slow": sql("SELECT count(*) FROM transactions a JOIN transactions b USING (account_id)"),
        "#many-rows": sql("SELECT transaction_id FROM transactions ORDER BY transaction_id"),
        "#declined": {
            "sql": None,
            "explanation": "Személyes adatot nem tudok lekérdezni.",
            "assumptions": [],
        },
        "#llm-down": LLMError(),
    }
)


def make_client(urls: DbUrls, **overrides: Any) -> TestClient:
    settings = make_settings(
        async_url(urls.app), llm_database_url=async_url(urls.llm_reader), **overrides
    )
    return TestClient(create_app(settings, llm_client=FAKE))


@pytest.fixture(scope="module")
def client(seeded_db: DbUrls) -> Iterator[TestClient]:
    users = [*DEMO_USERS, NewUser(BUDGET_USER, "Keret Klára", UserRole.ANALYST)]
    asyncio.run(create_users(seeded_db.migrator, users, PASSWORD))
    with make_client(seeded_db) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def tokens(client: TestClient) -> dict[str, dict[str, str]]:
    return {
        email: bearer(login(client, email))
        for email in (ANALYST, PECS_MANAGER, AUDITOR, ADMIN, BUDGET_USER)
    }


def ask(client: TestClient, headers: dict[str, str], question: str) -> Any:
    return client.post("/query", headers=headers, json={"question": question})


def log_rows(urls: DbUrls, question: str) -> list[tuple[Any, ...]]:
    """(attempt, status, rejection_reason) of every attempt at one question."""
    return as_owner(
        urls,
        "SELECT attempt, status::text, rejection_reason FROM app.query_log "
        f"WHERE question = '{question}' ORDER BY id",
    )


def calls_for(tag: str) -> int:
    return sum(tag in call.prompt for call in FAKE.calls)


def test_question_is_answered_and_logged(
    client: TestClient, tokens: dict[str, dict[str, str]], seeded_db: DbUrls
) -> None:
    question = "Hány 90+ napos késedelmes hitelünk van? #example"
    response = ask(client, tokens[ANALYST], question)

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["status"], body["columns"], body["attempts"]) == ("ok", ["loans"], 1)
    ((expected,),) = as_reader(seeded_db, NINETY_PLUS, scope="all")
    assert body["rows"] == [[expected]]
    assert body["sql"].endswith("LIMIT 200")
    assert log_rows(seeded_db, question) == [(1, "ok", None)]
    ((model, prompt_version, scope, tokens_used),) = as_owner(
        seeded_db,
        "SELECT model, prompt_version, scope, input_tokens + output_tokens FROM app.query_log "
        f"WHERE id = {body['query_id']}",
    )
    assert (model, prompt_version, scope) == ("fake", "text_to_sql.v1", "all")
    assert tokens_used > 0


def test_branch_manager_sees_only_the_own_branch(
    client: TestClient, tokens: dict[str, dict[str, str]], seeded_db: DbUrls
) -> None:
    as_manager = ask(client, tokens[PECS_MANAGER], "Számlák fiókonként #accounts-by-branch")
    as_analyst = ask(client, tokens[ANALYST], "Számlák fiókonként #accounts-by-branch")

    assert as_manager.status_code == as_analyst.status_code == 200
    assert [row[0] for row in as_manager.json()["rows"]] == [branch_id(seeded_db, "PEC01")]
    assert len(as_analyst.json()["rows"]) > 1


@pytest.mark.parametrize(
    ("tag", "reason"),
    [
        ("#delete", "forbidden_statement"),
        ("#set-config", "forbidden_function"),
        ("#pii", "forbidden_table"),
    ],
)
def test_forbidden_sql_is_rejected_logged_and_not_retried(
    client: TestClient,
    tokens: dict[str, dict[str, str]],
    seeded_db: DbUrls,
    tag: str,
    reason: str,
) -> None:
    question = f"Tiltott kérés {tag}"
    before = calls_for(tag)
    response = ask(client, tokens[PECS_MANAGER], question)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "sql_rejected"
    assert error["details"][0]["query_id"] > 0
    assert calls_for(tag) - before == 1  # no second chance for a forbidden intent
    ((attempt, status, rejection),) = log_rows(seeded_db, question)
    assert (attempt, status) == (1, "rejected_validation")
    assert rejection.startswith(reason)


def test_nothing_was_deleted(seeded_db: DbUrls) -> None:
    ((count,),) = as_owner(seeded_db, "SELECT count(*) FROM bank.transactions")

    assert count > 0


@pytest.mark.parametrize(
    ("tag", "first_status"),
    [("#repair-column", "sql_error"), ("#repair-view", "rejected_validation")],
)
def test_a_slip_is_repaired_with_the_error_fed_back(
    client: TestClient,
    tokens: dict[str, dict[str, str]],
    seeded_db: DbUrls,
    tag: str,
    first_status: str,
) -> None:
    question = f"Hány 90 napon túl késő hitel van? {tag}"
    response = ask(client, tokens[ANALYST], question)

    assert response.status_code == 200, response.text
    assert response.json()["attempts"] == 2
    statuses = [(attempt, status) for attempt, status, _ in log_rows(seeded_db, question)]
    assert statuses == [(1, first_status), (2, "ok")]
    repair_prompt = [call.prompt for call in FAKE.calls if tag in call.prompt][-1]
    assert "Előző SQL:" in repair_prompt
    assert "Hiba:" in repair_prompt


def test_repair_rounds_are_limited(
    client: TestClient, tokens: dict[str, dict[str, str]], seeded_db: DbUrls
) -> None:
    question = "Mindig hibás #never-right"
    response = ask(client, tokens[ANALYST], question)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "sql_error"
    assert [row[:2] for row in log_rows(seeded_db, question)] == [
        (1, "sql_error"),
        (2, "sql_error"),
        (3, "sql_error"),
    ]


def test_expensive_query_is_stopped_before_it_runs(
    client: TestClient, tokens: dict[str, dict[str, str]], seeded_db: DbUrls
) -> None:
    question = "Kereszt-JOIN #cross-join"
    response = ask(client, tokens[ANALYST], question)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "query_too_expensive"
    ((status, cost),) = as_owner(
        seeded_db,
        f"SELECT status::text, explain_cost FROM app.query_log WHERE question = '{question}'",
    )
    assert status == "rejected_cost"
    assert cost > 0


def test_slow_query_hits_the_statement_timeout(
    seeded_db: DbUrls, tokens: dict[str, dict[str, str]]
) -> None:
    question = "Lassú lekérdezés #slow"
    with make_client(seeded_db, sql_statement_timeout_ms=20) as slow_client:
        response = ask(slow_client, tokens[ANALYST], question)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "query_timeout"
    assert [row[:2] for row in log_rows(seeded_db, question)] == [(1, "timeout")]


def test_limit_is_enforced_and_reported(
    client: TestClient, tokens: dict[str, dict[str, str]]
) -> None:
    body = ask(client, tokens[ANALYST], "Minden tranzakció #many-rows").json()

    assert (body["row_count"], body["limit_reached"]) == (200, True)


def test_declined_question_is_an_answer_without_sql(
    client: TestClient, tokens: dict[str, dict[str, str]], seeded_db: DbUrls
) -> None:
    question = "Kik a legnagyobb adósok név szerint? #declined"
    response = ask(client, tokens[ANALYST], question)

    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["sql"], body["rows"]) == ("declined", None, [])
    assert body["explanation"] == "Személyes adatot nem tudok lekérdezni."
    assert [row[:2] for row in log_rows(seeded_db, question)] == [(1, "declined")]


def test_llm_failure_is_503_and_logged(
    client: TestClient, tokens: dict[str, dict[str, str]], seeded_db: DbUrls
) -> None:
    question = "Bármi #llm-down"
    response = ask(client, tokens[ANALYST], question)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "llm_unavailable"
    assert [row[:2] for row in log_rows(seeded_db, question)] == [(1, "llm_error")]


def test_daily_token_budget_stops_further_questions(
    client: TestClient, tokens: dict[str, dict[str, str]], seeded_db: DbUrls
) -> None:
    with psycopg.connect(seeded_db.conninfo("migrator")) as conn:
        conn.execute(
            "UPDATE app.users SET daily_token_budget = 100 WHERE email = %s", (BUDGET_USER,)
        )
    first = ask(client, tokens[BUDGET_USER], "Első kérdés #example")  # within budget: runs
    second = ask(client, tokens[BUDGET_USER], "Második kérdés #example")

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "token_budget_exceeded"
    assert [row[:2] for row in log_rows(seeded_db, "Második kérdés #example")] == [
        (1, "rejected_budget")
    ]


def test_auditor_reads_the_log_but_cannot_query(
    client: TestClient, tokens: dict[str, dict[str, str]]
) -> None:
    as_auditor = client.get("/audit/queries?status=rejected_validation", headers=tokens[AUDITOR])

    assert ask(client, tokens[AUDITOR], "Bármi #example").status_code == 403
    assert as_auditor.status_code == 200
    assert as_auditor.json()
    assert {row["status"] for row in as_auditor.json()} == {"rejected_validation"}
    assert client.get("/audit/queries", headers=tokens[ANALYST]).status_code == 403


def test_history_shows_only_the_own_queries(
    client: TestClient, tokens: dict[str, dict[str, str]], seeded_db: DbUrls
) -> None:
    ask(client, tokens[PECS_MANAGER], "Pécsi kérdés #example")
    history = client.get("/query/history?limit=200", headers=tokens[PECS_MANAGER]).json()
    ((manager_id,),) = as_owner(
        seeded_db, f"SELECT id::text FROM app.users WHERE email = '{PECS_MANAGER}'"
    )

    assert history
    assert {row["user_id"] for row in history} == {manager_id}
    assert history[0]["question"] == "Pécsi kérdés #example"  # newest first


def test_schema_shows_the_views_without_pii(
    client: TestClient, tokens: dict[str, dict[str, str]]
) -> None:
    response = client.get("/schema", headers=tokens[PECS_MANAGER])

    assert response.status_code == 200
    views = {view["name"]: view for view in response.json()["views"]}
    assert {"transactions", "loans", "customers", "business_day"} <= views.keys()
    columns = {c["name"] for view in views.values() for c in view["columns"]}
    assert not columns & {"full_name", "tax_id", "iban", "birth_date", "description"}
    channel = next(c for c in views["transactions"]["columns"] if c["name"] == "channel")
    assert channel["enum_values"] == ["card", "transfer", "atm", "direct_debit", "fee", "interest"]


def test_query_log_is_append_only(seeded_db: DbUrls) -> None:
    for statement in ("UPDATE app.query_log SET status = 'ok'", "DELETE FROM app.query_log"):
        with (
            psycopg.connect(seeded_db.conninfo("app")) as conn,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            conn.execute(statement)

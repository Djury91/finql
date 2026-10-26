"""Dynamic few-shot against the real database: the curated examples, their sync, the selection,
and the API path (prompt and query log)."""

import asyncio
from collections.abc import Iterator, Sequence

import pytest
from fastapi.testclient import TestClient

from finql.auth.admin import DEMO_USERS, create_users
from finql.core.db import async_url, create_engine, create_sessionmaker
from finql.llm.embeddings import EmbeddingError, HashingEmbedder, InputType
from finql.llm.fake_client import FakeLLMClient
from finql.main import create_app
from finql.text_to_sql.examples import (
    ExampleSelector,
    ExampleSpec,
    SyncResult,
    check_example,
    load_example_file,
    sync_examples,
)
from finql.text_to_sql.schema_context import load_catalog
from tests.helpers import make_settings

from .api import ANALYST, PASSWORD, bearer, login
from .db import DbUrls
from .test_security import as_owner

pytestmark = pytest.mark.integration

EXAMPLES = load_example_file()


@pytest.mark.parametrize("spec", EXAMPLES, ids=lambda spec: spec.question[:40])
async def test_every_example_passes_the_validator_and_runs(
    seeded_db: DbUrls, spec: ExampleSpec
) -> None:
    engine = create_engine(async_url(seeded_db.llm_reader))
    try:
        settings = make_settings(async_url(seeded_db.app))
        await check_example(
            spec, engine=engine, catalog=await load_catalog(engine), settings=settings
        )
    finally:
        await engine.dispose()


class OtherModel(HashingEmbedder):
    model = "hashing-other"


async def sync(urls: DbUrls, specs: Sequence[ExampleSpec], embedder: HashingEmbedder) -> SyncResult:
    engine = create_engine(async_url(urls.app))
    try:
        return await sync_examples(create_sessionmaker(engine), embedder, specs)
    finally:
        await engine.dispose()


async def select(urls: DbUrls, question: str, embedder: HashingEmbedder, k: int) -> list[str]:
    engine = create_engine(async_url(urls.app))
    try:
        selector = ExampleSelector(create_sessionmaker(engine), embedder, k)
        return [example.question for example in await selector.select(question)]
    finally:
        await engine.dispose()


LOANS = ExampleSpec(question="Hány hitel késik?", sql="SELECT count(*) FROM loans")
CARDS = ExampleSpec(question="Hány kártya aktív?", sql="SELECT count(*) FROM cards")
BRANCHES = ExampleSpec(question="Hány fiók van?", sql="SELECT count(*) FROM branches")


async def test_sync_inserts_updates_and_deactivates(seeded_db: DbUrls) -> None:
    hashing = HashingEmbedder()

    first = await sync(seeded_db, [LOANS, CARDS], hashing)
    again = await sync(seeded_db, [LOANS, CARDS], hashing)
    changed_loans = LOANS.model_copy(update={"sql": "SELECT count(*) AS n FROM loans"})
    changed = await sync(seeded_db, [changed_loans, BRANCHES], hashing)

    assert (first.added, again.unchanged) == (2, 2)
    assert (changed.added, changed.updated, changed.deactivated) == (1, 1, 1)
    ((sql,),) = as_owner(
        seeded_db, "SELECT sql FROM app.sql_examples WHERE question = 'Hány hitel késik?'"
    )
    assert sql == changed_loans.sql
    # The deactivated one is never selected.
    assert "Hány kártya aktív?" not in await select(seeded_db, "Hány kártya aktív?", hashing, 5)


async def test_a_new_embedding_model_re_embeds_and_old_vectors_are_not_compared(
    seeded_db: DbUrls,
) -> None:
    await sync(seeded_db, [LOANS, CARDS], HashingEmbedder())

    switched = await sync(seeded_db, [LOANS, CARDS], OtherModel())

    assert switched.updated == 2
    assert await select(seeded_db, "Hány hitel késik?", HashingEmbedder(), 3) == []
    assert len(await select(seeded_db, "Hány hitel késik?", OtherModel(), 3)) == 2


async def test_selection_returns_the_most_similar_examples(seeded_db: DbUrls) -> None:
    await sync(seeded_db, EXAMPLES, HashingEmbedder())

    chosen = await select(
        seeded_db, "Hány százaléka késik a hiteleknek fiókonként?", HashingEmbedder(), 3
    )

    assert len(chosen) == 3
    assert "Fiókonként az élő hitelek hány százaléka késik 30 napnál többet?" in chosen


# --- the API path ----------------------------------------------------------------------------

FEW_SHOT_QUESTION = "Hány százaléka késik a hiteleknek fiókonként? #few-shot"
FAKE = FakeLLMClient(
    rules={
        "#few-shot": {
            "sql": "SELECT count(*) FROM loans WHERE days_past_due > 0",
            "explanation": "Teszt.",
            "assumptions": [],
        }
    }
)


class BrokenEmbedder(HashingEmbedder):
    async def embed(self, texts: Sequence[str], *, input_type: InputType) -> list[list[float]]:
        raise EmbeddingError()


def app_client(urls: DbUrls, embedder: HashingEmbedder) -> TestClient:
    settings = make_settings(
        async_url(urls.app), llm_database_url=async_url(urls.llm_reader), few_shot_k=2
    )
    return TestClient(create_app(settings, llm_client=FAKE, embedder=embedder))


@pytest.fixture(scope="module")
def users(seeded_db: DbUrls) -> None:
    asyncio.run(create_users(seeded_db.migrator, list(DEMO_USERS), PASSWORD))


def ask(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/query",
        headers=bearer(login(client, ANALYST)),
        json={"question": FEW_SHOT_QUESTION},
    )
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


@pytest.fixture
def examples_loaded(seeded_db: DbUrls) -> Iterator[None]:
    asyncio.run(sync(seeded_db, EXAMPLES, HashingEmbedder()))
    yield


def test_examples_reach_the_prompt_and_the_query_log(
    seeded_db: DbUrls, users: None, examples_loaded: None
) -> None:
    with app_client(seeded_db, HashingEmbedder()) as client:
        body = ask(client)

    prompt = FAKE.calls[-1].prompt
    assert prompt.startswith("Hasonló kérdések bevált lekérdezéssel.")
    assert "Fiókonként az élő hitelek hány százaléka késik 30 napnál többet?" in prompt
    ((example_ids, questions),) = as_owner(
        seeded_db,
        "SELECT q.example_ids, array(SELECT e.question FROM app.sql_examples e "
        "WHERE e.id = ANY (q.example_ids)) "
        f"FROM app.query_log q WHERE q.id = {body['query_id']}",
    )
    assert len(example_ids) == 2
    assert all(question in prompt for question in questions)


def test_an_embedding_outage_costs_the_examples_not_the_answer(
    seeded_db: DbUrls, users: None, examples_loaded: None
) -> None:
    with app_client(seeded_db, BrokenEmbedder()) as client:
        body = ask(client)

    assert body["status"] == "ok"
    assert FAKE.calls[-1].prompt == f"Kérdés: {FEW_SHOT_QUESTION}"
    ((example_ids,),) = as_owner(
        seeded_db, f"SELECT example_ids FROM app.query_log WHERE id = {body['query_id']}"
    )
    assert example_ids is None

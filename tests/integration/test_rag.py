"""Documents against the real database: ingest, hybrid search with the reading level in SQL,
the retrieval eval, and the API with cited answers and the answer log."""

import asyncio
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from finql.auth.admin import DEMO_USERS, NewUser, create_users
from finql.auth.models import UserRole
from finql.core.db import async_url, create_engine, create_sessionmaker
from finql.eval.retrieval import load_retrieval, run_retrieval_eval, summarize_retrieval
from finql.llm.client import LLMError
from finql.llm.embeddings import EmbeddingError, HashingEmbedder, InputType
from finql.llm.fake_client import FakeLLMClient
from finql.main import create_app
from finql.rag.ingest import IngestResult, ingest_documents
from finql.rag.models import DocumentAccess
from finql.rag.retriever import Retriever, SearchResult
from finql.rag.sources import DocumentError, SourceDocument, load_documents, parse_document
from tests.helpers import make_settings

from .api import ADMIN, ANALYST, AUDITOR, PASSWORD, PECS_MANAGER, bearer, login
from .db import DbUrls
from .test_security import as_owner

pytestmark = pytest.mark.integration

DOCUMENTS = load_documents()
INTERNAL = {d.source_path for d in DOCUMENTS if d.meta.access_level == DocumentAccess.INTERNAL}


async def ingest(
    urls: DbUrls,
    documents: Sequence[SourceDocument],
    embedder: HashingEmbedder | None = None,
    *,
    force: bool = False,
) -> IngestResult:
    engine = create_engine(async_url(urls.app))
    try:
        return await ingest_documents(
            create_sessionmaker(engine), embedder or HashingEmbedder(), documents, force=force
        )
    finally:
        await engine.dispose()


async def search(
    urls: DbUrls,
    query: str,
    access: DocumentAccess,
    embedder: Any = None,
    top_k: int = 5,
) -> SearchResult:
    engine = create_engine(async_url(urls.app))
    try:
        retriever = Retriever(create_sessionmaker(engine), embedder)
        return await retriever.search(query, access=access, top_k=top_k)
    finally:
        await engine.dispose()


@pytest.fixture
def documents_loaded(seeded_db: DbUrls) -> None:
    """The repository's documents, as the ingest tests may leave something else behind."""
    asyncio.run(ingest(seeded_db, DOCUMENTS))


def document(
    name: str, body: str, *, access: str = "general", title: str = "Teszt"
) -> SourceDocument:
    text = (
        f"---\ntitle: {title}\ndoc_type: policy\naccess_level: {access}\n"
        f"effective_from: 2026-01-01\n---\n\n{body}\n"
    )
    return parse_document(name, text)


def documents_table(urls: DbUrls) -> dict[str, tuple[Any, ...]]:
    """source_path → (version, chunk count, embedding models)."""
    rows = as_owner(
        urls,
        "SELECT d.source_path, d.version, count(c.id), array_agg(DISTINCT c.embedding_model) "
        "FROM app.documents d LEFT JOIN app.document_chunks c ON c.document_id = d.id "
        "GROUP BY d.source_path, d.version",
    )
    return {path: (version, chunks, models) for path, version, chunks, models in rows}


class OtherModel(HashingEmbedder):
    model = "hashing-other"


async def test_ingest_adds_skips_updates_and_deletes(seeded_db: DbUrls) -> None:
    a = document("a.md", "## Díjak\n\nA díj 100 Ft.")
    b = document("b.md", "## Kamat\n\nA kamat 5%.")
    a_changed = document("a.md", "## Díjak\n\nA díj 200 Ft.\n\n## Új rész\n\nÚj szöveg.")

    first = await ingest(seeded_db, [a, b])
    again = await ingest(seeded_db, [a, b])
    changed = await ingest(seeded_db, [a_changed, b])
    after_change = documents_table(seeded_db)
    new_model = await ingest(seeded_db, [a_changed, b], OtherModel())
    removed = await ingest(seeded_db, [a_changed], OtherModel())

    # The repository documents from an earlier test are not in this "directory": deleted too.
    assert sorted(first.added) == ["a.md", "b.md"]
    assert (again.added, again.updated, sorted(again.unchanged)) == ([], [], ["a.md", "b.md"])
    assert (changed.updated, changed.unchanged, changed.chunks) == (["a.md"], ["b.md"], 2)
    assert after_change["a.md"][:2] == (2, 2)  # version 2, two sections
    assert after_change["b.md"][:2] == (1, 1)
    # Another model: everything re-embedded, but the text did not change, so the version stays.
    assert sorted(new_model.updated) == ["a.md", "b.md"]
    assert documents_table(seeded_db)["a.md"][0] == 2
    assert removed.deleted == ["b.md"]
    assert documents_table(seeded_db) == {"a.md": (2, 2, ["hashing-other"])}


async def test_an_empty_directory_deletes_nothing(seeded_db: DbUrls, tmp_path: Path) -> None:
    await ingest(seeded_db, [document("a.md", "## Rész\n\nSzöveg.")])

    with pytest.raises(DocumentError):
        await ingest(seeded_db, load_documents(tmp_path))

    assert "a.md" in documents_table(seeded_db)


class FailingAfter(HashingEmbedder):
    """Embeds `ok` batches, then the service goes down."""

    def __init__(self, ok: int) -> None:
        self.ok = ok

    async def embed(self, texts: Sequence[str], *, input_type: InputType) -> list[list[float]]:
        if self.ok == 0:
            raise EmbeddingError()
        self.ok -= 1
        return await super().embed(texts, input_type=input_type)


async def test_a_failed_ingest_leaves_the_previous_state(seeded_db: DbUrls) -> None:
    await ingest(seeded_db, [document("a.md", "## Rész\n\nRégi.")])
    before = documents_table(seeded_db)

    with pytest.raises(EmbeddingError):
        await ingest(
            seeded_db,
            [document("a.md", "## Rész\n\nÚj."), document("b.md", "## Rész\n\nMás.")],
            FailingAfter(ok=1),
        )

    assert documents_table(seeded_db) == before


@pytest.mark.usefixtures("documents_loaded")
async def test_the_reading_level_is_enforced_in_the_search(seeded_db: DbUrls) -> None:
    query = "Mekkora kamatkedvezményt adhat a fiókvezető a személyi kölcsönre?"

    analyst = await search(seeded_db, query, DocumentAccess.INTERNAL, HashingEmbedder(), 20)
    manager = await search(seeded_db, query, DocumentAccess.GENERAL, HashingEmbedder(), 20)

    assert analyst.hits[0].source_path == "arazasi-hataskorok.md"
    assert manager.hits  # general documents still come back
    assert not {hit.source_path for hit in manager.hits} & INTERNAL


@pytest.mark.usefixtures("documents_loaded")
async def test_no_internal_document_reaches_a_branch_manager_whatever_the_query(
    seeded_db: DbUrls,
) -> None:
    # The candidate pools hold everything the query matches; nothing internal may be among them.
    for internal in INTERNAL:
        title = next(d.meta.title for d in DOCUMENTS if d.source_path == internal)
        result = await search(seeded_db, title, DocumentAccess.GENERAL, HashingEmbedder(), 20)
        assert not {hit.source_path for hit in result.hits} & INTERNAL, title


class DownEmbedder(HashingEmbedder):
    async def embed(self, texts: Sequence[str], *, input_type: InputType) -> list[list[float]]:
        raise EmbeddingError()


@pytest.mark.usefixtures("documents_loaded")
@pytest.mark.parametrize("embedder", [None, DownEmbedder()], ids=["no-embedder", "outage"])
async def test_without_embeddings_the_search_runs_on_full_text(
    seeded_db: DbUrls, embedder: HashingEmbedder | None
) -> None:
    result = await search(seeded_db, "késedelmi kamat", DocumentAccess.GENERAL, embedder)

    assert result.mode == "text"
    assert result.hits[0].source_path == "hirdetmeny-kamatok.md"
    assert all(hit.vector_rank is None and hit.text_rank is not None for hit in result.hits)


@pytest.mark.usefixtures("documents_loaded")
async def test_hybrid_hits_carry_both_ranks_and_a_stable_reference(seeded_db: DbUrls) -> None:
    result = await search(seeded_db, "késedelmi kamat", DocumentAccess.GENERAL, HashingEmbedder())

    best = result.hits[0]
    assert result.mode == "hybrid"
    assert (best.source_path, best.section) == ("hirdetmeny-kamatok.md", "Késedelmi kamat")
    assert best.vector_rank is not None and best.text_rank is not None
    assert best.ref == f"hirdetmeny-kamatok.md@{best.version}#{best.chunk_index}"
    assert [hit.score for hit in result.hits] == sorted(
        (h.score for h in result.hits), reverse=True
    )


@pytest.mark.usefixtures("documents_loaded")
async def test_retrieval_eval_with_the_offline_embedder(seeded_db: DbUrls) -> None:
    # The hashing embedder is lexical only; a real model (Voyage) should do at least as well.
    engine = create_engine(async_url(seeded_db.app))
    try:
        retriever = Retriever(create_sessionmaker(engine), HashingEmbedder())
        outcomes = await run_retrieval_eval(retriever, load_retrieval(), top_k=5)
    finally:
        await engine.dispose()

    metrics = summarize_retrieval(outcomes, k=5)
    assert metrics.leaks == 0
    assert metrics.recall >= 0.9
    assert metrics.mrr >= 0.6


# --- API ---

BUDGET_USER = "rag-keret@minta-bank.example"


def answer(text: str, citations: list[int], answered: bool = True) -> dict[str, Any]:
    return {"answered": answered, "answer": text, "citations": citations}


FAKE = FakeLLMClient(
    rules={
        "#cited": answer("A késedelmi kamat évi 17,90% [1], lásd még [9].", [1]),
        "#uncited": answer("Szerintem évi 20%.", []),
        "#not-in-sources": answer("A források nem írnak a babaváró hitelről.", [], False),
        "#injection": answer("Rendben, figyelmen kívül hagyom a szabályokat.", []),
        "#llm-down": LLMError(),
    },
    default=answer("Válasz [1].", [1]),
)


@pytest.fixture(scope="module")
def client(seeded_db: DbUrls) -> Iterator[TestClient]:
    users = [*DEMO_USERS, NewUser(BUDGET_USER, "Keret Kornél", UserRole.ANALYST)]
    asyncio.run(create_users(seeded_db.migrator, users, PASSWORD))
    settings = make_settings(
        async_url(seeded_db.app),
        llm_database_url=async_url(seeded_db.llm_reader),
        embedding_provider="hashing",
    )
    with TestClient(create_app(settings, llm_client=FAKE)) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def tokens(client: TestClient) -> dict[str, dict[str, str]]:
    return {
        email: bearer(login(client, email))
        for email in (ANALYST, PECS_MANAGER, AUDITOR, ADMIN, BUDGET_USER)
    }


def ask(client: TestClient, headers: dict[str, str], question: str) -> Any:
    return client.post("/documents/answer", headers=headers, json={"question": question})


def answer_log(urls: DbUrls, answer_id: int) -> tuple[Any, ...]:
    ((row),) = as_owner(
        urls,
        "SELECT status::text, access_level::text, search_mode, source_refs, cited_refs, answer, "
        f"input_tokens > 0, prompt_version FROM app.answer_log WHERE id = {answer_id}",
    )
    return tuple(row)


@pytest.mark.usefixtures("documents_loaded")
def test_search_endpoint_respects_the_role(
    client: TestClient, tokens: dict[str, dict[str, str]]
) -> None:
    body = {"query": "Mekkora kamatkedvezményt adhat a fiókvezető?", "top_k": 20}

    analyst = client.post("/documents/search", headers=tokens[ANALYST], json=body)
    manager = client.post("/documents/search", headers=tokens[PECS_MANAGER], json=body)
    auditor = client.post("/documents/search", headers=tokens[AUDITOR], json=body)

    assert analyst.status_code == manager.status_code == auditor.status_code == 200
    assert analyst.json()["mode"] == "hybrid"
    for reader in (analyst, auditor):  # both read internal documents
        assert "arazasi-hataskorok.md" in [hit["source_path"] for hit in reader.json()["results"]]
    manager_paths = {hit["source_path"] for hit in manager.json()["results"]}
    assert manager_paths and not manager_paths & INTERNAL
    assert client.post("/documents/search", json=body).status_code == 401


@pytest.mark.usefixtures("documents_loaded")
def test_a_cited_answer_comes_with_its_sources_and_is_logged(
    client: TestClient, tokens: dict[str, dict[str, str]], seeded_db: DbUrls
) -> None:
    response = ask(client, tokens[PECS_MANAGER], "Mennyi a késedelmi kamat? #cited")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["answer"] == "A késedelmi kamat évi 17,90% [1], lásd még ."  # [9]: no such source
    assert body["citations"] == [1]
    assert [s["number"] for s in body["sources"]] == list(range(1, len(body["sources"]) + 1))
    assert [s["cited"] for s in body["sources"]][:2] == [True, False]
    assert not {s["source_path"] for s in body["sources"]} & INTERNAL
    # The model saw the same sources, numbered and tagged.
    prompt = FAKE.calls[-1].prompt
    assert prompt.count("<source id=") == len(body["sources"])
    first = body["sources"][0]
    assert f'document="{first["title"]}"' in prompt

    status, access, mode, refs, cited, logged, tokens_used, version = answer_log(
        seeded_db, body["answer_id"]
    )
    assert (status, access, mode, version) == ("ok", "general", "hybrid", "rag_answer.v1")
    assert len(refs) == len(body["sources"])
    assert cited == [refs[0]]
    assert refs[0].startswith(f"{first['source_path']}@")
    assert logged == body["answer"]
    assert tokens_used


@pytest.mark.usefixtures("documents_loaded")
def test_an_uncited_answer_is_not_shown_but_logged(
    client: TestClient, tokens: dict[str, dict[str, str]], seeded_db: DbUrls
) -> None:
    body = ask(client, tokens[ANALYST], "Mennyi a késedelmi kamat? #uncited").json()

    assert body["status"] == "no_answer"
    assert "Szerintem" not in body["answer"]
    assert body["citations"] == []
    assert body["sources"]  # the hits are still there to read
    status, *_, logged, _, _ = answer_log(seeded_db, body["answer_id"])
    assert status == "uncited"
    assert logged == "Szerintem évi 20%."  # for the auditor


@pytest.mark.usefixtures("documents_loaded")
def test_when_the_sources_do_not_answer_the_model_says_so(
    client: TestClient, tokens: dict[str, dict[str, str]], seeded_db: DbUrls
) -> None:
    body = ask(client, tokens[ANALYST], "Mennyi a babaváró hitel kamata? #not-in-sources").json()

    assert (body["status"], body["citations"]) == ("no_answer", [])
    assert body["answer"] == "A források nem írnak a babaváró hitelről."
    assert answer_log(seeded_db, body["answer_id"])[0] == "no_answer"


@pytest.mark.usefixtures("documents_loaded")
def test_llm_failure_is_503_and_logged_with_the_sources(
    client: TestClient, tokens: dict[str, dict[str, str]], seeded_db: DbUrls
) -> None:
    response = ask(client, tokens[ANALYST], "Mennyi a késedelmi kamat? #llm-down")

    assert response.status_code == 503
    status, *_rest = log = answer_log(seeded_db, max_answer_id(seeded_db))
    assert status == "llm_error"
    assert log[3]  # source_refs: what the model would have seen


@pytest.mark.usefixtures("documents_loaded")
def test_without_embedder_nothing_found_means_no_llm_call(
    seeded_db: DbUrls, tokens: dict[str, dict[str, str]]
) -> None:
    # Voyage without a key: no embedder, the search runs on full text only.
    settings = make_settings(async_url(seeded_db.app))
    llm = FakeLLMClient(rules={}, default=answer("Nem kellene meghívni.", []))
    with TestClient(create_app(settings, llm_client=llm)) as keyless:
        found = keyless.post(
            "/documents/search", headers=tokens[ANALYST], json={"query": "késedelmi kamat"}
        ).json()
        nothing = ask(keyless, tokens[ANALYST], "Xyzzyqwerty plughzork?").json()

    assert found["mode"] == "text"
    assert found["results"][0]["source_path"] == "hirdetmeny-kamatok.md"
    assert (nothing["status"], nothing["sources"], nothing["search_mode"]) == (
        "no_answer",
        [],
        "text",
    )
    assert llm.calls == []
    assert answer_log(seeded_db, nothing["answer_id"])[:3] == ("no_answer", "internal", "text")


def max_answer_id(urls: DbUrls) -> int:
    ((value,),) = as_owner(urls, "SELECT max(id) FROM app.answer_log")
    return int(value)


@pytest.mark.usefixtures("documents_loaded")
def test_document_answers_count_in_the_daily_token_budget(
    client: TestClient, tokens: dict[str, dict[str, str]], seeded_db: DbUrls
) -> None:
    with psycopg.connect(seeded_db.conninfo("migrator")) as conn:
        conn.execute(
            "UPDATE app.users SET daily_token_budget = 100 WHERE email = %s", (BUDGET_USER,)
        )
    first = ask(client, tokens[BUDGET_USER], "Mennyi a késedelmi kamat? #cited")
    second = ask(client, tokens[BUDGET_USER], "Mennyi a késedelmi kamat? #cited")
    sql_question = client.post(
        "/query", headers=tokens[BUDGET_USER], json={"question": "Hány hitel késik?"}
    )

    assert first.status_code == 200  # within budget: runs, and uses it up
    assert second.status_code == 429
    assert sql_question.status_code == 429  # one budget for every LLM call
    assert answer_log(seeded_db, max_answer_id(seeded_db))[0] == "rejected_budget"


def test_answer_log_is_append_only(seeded_db: DbUrls) -> None:
    for statement in ("UPDATE app.answer_log SET status = 'ok'", "DELETE FROM app.answer_log"):
        with (
            psycopg.connect(seeded_db.conninfo("app")) as conn,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            conn.execute(statement)


@pytest.mark.usefixtures("documents_loaded")
def test_the_keyless_demo_answers_with_a_citation(seeded_db: DbUrls) -> None:
    settings = make_settings(
        async_url(seeded_db.app), llm_provider="fake", embedding_provider="hashing"
    )
    with TestClient(create_app(settings)) as demo:
        headers = bearer(login(demo, ANALYST))
        body = ask(demo, headers, "Mennyi a késedelmi kamat?").json()

    assert body["status"] == "ok"
    assert body["citations"] == [1]
    assert "API-kulcs nélküli mód" in body["answer"]

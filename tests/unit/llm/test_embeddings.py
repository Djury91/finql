"""Embedders: Voyage against a mocked HTTP transport (no network, no key), and the hashing one."""

import json
import math
from collections.abc import Callable
from typing import Any

import httpx2 as httpx
import pytest

from finql.llm.embeddings import (
    EMBEDDING_DIMENSIONS,
    EmbeddingError,
    HashingEmbedder,
    VoyageEmbedder,
    build_embedder,
)
from tests.helpers import make_settings

UNUSED_DB = "postgresql+asyncpg://user:pass@127.0.0.1:1/finql"


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def voyage_answer(request: httpx.Request) -> httpx.Response:
    texts = json.loads(request.content)["input"]
    # Reversed on purpose: the client must order by `index`, not by position.
    data = [
        {"object": "embedding", "index": i, "embedding": [float(i)] * EMBEDDING_DIMENSIONS}
        for i in reversed(range(len(texts)))
    ]
    return httpx.Response(200, json={"data": data, "usage": {"total_tokens": 10}})


def voyage_with(
    respond: Callable[[httpx.Request], httpx.Response],
    waits: list[float] | None = None,
) -> tuple[VoyageEmbedder, list[httpx.Request]]:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return respond(request)

    async def sleep(seconds: float) -> None:  # records instead of waiting
        if waits is not None:
            waits.append(seconds)

    settings = make_settings(UNUSED_DB, voyage_api_key="test-key")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return VoyageEmbedder(settings, client=client, sleep=sleep), sent


def responses(*answers: httpx.Response) -> Callable[[httpx.Request], httpx.Response]:
    """The given responses in order, then a successful one."""
    queue = list(answers)
    return lambda request: queue.pop(0) if queue else voyage_answer(request)


async def test_voyage_request_shape_and_answer_order() -> None:
    embedder, sent = voyage_with(voyage_answer)

    vectors = await embedder.embed(["első", "második"], input_type="query")

    body: dict[str, Any] = json.loads(sent[0].content)
    assert sent[0].url == VoyageEmbedder.URL
    assert sent[0].headers["authorization"] == "Bearer test-key"
    assert body == {
        "input": ["első", "második"],
        "model": "voyage-4",
        "input_type": "query",
        "output_dimension": EMBEDDING_DIMENSIONS,
    }
    assert [v[0] for v in vectors] == [0.0, 1.0]


async def test_voyage_splits_long_inputs_into_batches() -> None:
    embedder, sent = voyage_with(voyage_answer)

    vectors = await embedder.embed([f"szöveg {i}" for i in range(300)], input_type="document")

    assert [len(json.loads(r.content)["input"]) for r in sent] == [128, 128, 44]
    assert len(vectors) == 300


@pytest.mark.parametrize(
    "respond",
    [
        lambda _: httpx.Response(429, json={"detail": "rate limit"}),
        lambda _: httpx.Response(500),
        lambda _: httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]}),
    ],
    ids=["rate-limited", "server-error", "wrong-dimension"],
)
async def test_voyage_failures_become_embedding_errors(
    respond: Callable[[httpx.Request], httpx.Response],
) -> None:
    embedder, _ = voyage_with(respond)

    with pytest.raises(EmbeddingError):
        await embedder.embed(["kérdés"], input_type="query")


async def test_a_rate_limit_is_retried_after_the_wait_the_service_asks_for() -> None:
    waits: list[float] = []
    embedder, sent = voyage_with(
        responses(httpx.Response(429, headers={"retry-after": "3"}), httpx.Response(503)), waits
    )

    vectors = await embedder.embed(["kérdés"], input_type="query")

    assert len(vectors) == 1
    assert len(sent) == 3
    assert waits == [3.0, 2.0]  # Retry-After, then the backoff of the second attempt


async def test_retries_are_limited() -> None:
    waits: list[float] = []
    embedder, sent = voyage_with(lambda _: httpx.Response(500), waits)

    with pytest.raises(EmbeddingError):
        await embedder.embed(["kérdés"], input_type="query")

    assert len(sent) == VoyageEmbedder.MAX_RETRIES + 1
    assert waits == [1.0, 2.0]


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(429, headers={"retry-after": "60"}),  # a per-minute quota: too long
        httpx.Response(400, json={"detail": "bad request"}),
        httpx.Response(401, json={"detail": "invalid key"}),
    ],
    ids=["long-retry-after", "bad-request", "bad-key"],
)
async def test_no_retry_when_waiting_would_not_help(response: httpx.Response) -> None:
    waits: list[float] = []
    embedder, sent = voyage_with(responses(response), waits)

    with pytest.raises(EmbeddingError):
        await embedder.embed(["kérdés"], input_type="query")

    assert len(sent) == 1 and waits == []


async def test_voyage_connection_failure_becomes_an_embedding_error() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    embedder, _ = voyage_with(refuse)

    with pytest.raises(EmbeddingError):
        await embedder.embed(["kérdés"], input_type="query")


async def test_hashing_vectors_are_deterministic_unit_vectors() -> None:
    embedder = HashingEmbedder()

    first, again = await embedder.embed(["Hány hitel késik?"] * 2, input_type="query")

    assert first == again
    assert len(first) == EMBEDDING_DIMENSIONS
    assert math.isclose(math.sqrt(sum(v * v for v in first)), 1.0)


def test_hashing_similarity_is_lexical() -> None:
    question = HashingEmbedder.vector("Hány késedelmes hitelünk van?")
    inflected = HashingEmbedder.vector("Mennyi a késedelmes hitelek összege?")
    unrelated = HashingEmbedder.vector("Melyik kereskedőnél költöttek legtöbbet kártyával?")

    assert cosine(question, inflected) > cosine(question, unrelated)


def test_build_embedder_follows_the_settings() -> None:
    assert isinstance(
        build_embedder(make_settings(UNUSED_DB, embedding_provider="hashing")), HashingEmbedder
    )
    # Voyage without a key: no embedder, dynamic few-shot stays off.
    assert build_embedder(make_settings(UNUSED_DB)) is None
    assert isinstance(
        build_embedder(make_settings(UNUSED_DB, voyage_api_key="key")), VoyageEmbedder
    )

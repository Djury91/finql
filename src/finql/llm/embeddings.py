"""Text embeddings behind a provider-independent protocol (ADR-004): Voyage AI, and a deterministic
hashing stand-in for tests and for running without an API key."""

import asyncio
import hashlib
import math
import re
import time
import unicodedata
from collections.abc import Awaitable, Callable, Sequence
from typing import Literal, Protocol

import httpx2 as httpx
import structlog
from opentelemetry import trace
from opentelemetry.semconv._incubating.attributes import gen_ai_attributes as gen_ai
from opentelemetry.trace import SpanKind

from finql.core.config import Settings
from finql.core.errors import AppError
from finql.core.telemetry import tracer

logger = structlog.get_logger(__name__)

# The vector(1024) columns of the database (app.sql_examples, later app.document_chunks).
EMBEDDING_DIMENSIONS = 1024

type InputType = Literal["query", "document"]


class EmbeddingError(AppError):
    status_code = 503
    code = "embedding_unavailable"
    message = "Az embedding-szolgáltatás most nem érhető el."


class Embedder(Protocol):
    @property
    def model(self) -> str:
        """Stored next to every vector: vectors of different models are not comparable."""
        ...

    async def embed(self, texts: Sequence[str], *, input_type: InputType) -> list[list[float]]:
        """One unit-length vector of EMBEDDING_DIMENSIONS floats per text, in input order.

        `input_type`: a question to search with ("query") or a text to be found ("document").
        """
        ...


class VoyageEmbedder:
    URL = "https://api.voyageai.com/v1/embeddings"
    # Well under the API limits (1000 texts, 320K tokens per request for voyage-4).
    BATCH_SIZE = 128
    # A rate limit (429) or a server error (5xx) is retried, but briefly: a question waits for
    # the answer. A longer Retry-After than the cap (a per-minute quota) fails at once.
    MAX_RETRIES = 2
    MAX_WAIT_SECONDS = 5.0

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if settings.voyage_api_key is None:
            raise ValueError("FINQL_VOYAGE_API_KEY is not set")
        self._model = settings.embedding_model
        self._client = client or httpx.AsyncClient(timeout=settings.embedding_timeout_seconds)
        self._headers = {"Authorization": f"Bearer {settings.voyage_api_key.get_secret_value()}"}
        self._sleep = sleep

    @property
    def model(self) -> str:
        return self._model

    async def embed(self, texts: Sequence[str], *, input_type: InputType) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[start : start + self.BATCH_SIZE]
            vectors.extend(await self._embed_batch(batch, input_type))
        return vectors

    async def _embed_batch(self, texts: Sequence[str], input_type: InputType) -> list[list[float]]:
        attributes: dict[str, str | int] = {
            gen_ai.GEN_AI_OPERATION_NAME: gen_ai.GenAiOperationNameValues.EMBEDDINGS.value,
            gen_ai.GEN_AI_PROVIDER_NAME: "voyage_ai",
            gen_ai.GEN_AI_REQUEST_MODEL: self._model,
            gen_ai.GEN_AI_EMBEDDINGS_DIMENSION_COUNT: EMBEDDING_DIMENSIONS,
        }
        with tracer.start_as_current_span(
            f"embeddings {self._model}", kind=SpanKind.CLIENT, attributes=attributes
        ):
            return await self._request(texts, input_type)

    async def _request(self, texts: Sequence[str], input_type: InputType) -> list[list[float]]:
        started = time.perf_counter()
        payload = {
            "input": list(texts),
            "model": self._model,
            "input_type": input_type,
            "output_dimension": EMBEDDING_DIMENSIONS,
        }
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                response = await self._client.post(self.URL, headers=self._headers, json=payload)
            except httpx.HTTPError as exc:  # connection, timeout
                logger.warning("embedding request failed", error=type(exc).__name__)
                raise EmbeddingError() from exc
            if not response.is_error:
                break
            wait = self._retry_wait(response, attempt)
            logger.warning("embedding request failed", status=response.status_code, retry_in=wait)
            trace.get_current_span().add_event(
                "retry" if wait is not None else "give up",
                {"http.response.status_code": response.status_code},
            )
            if wait is None:
                raise EmbeddingError()
            await self._sleep(wait)
        body = response.json()
        data = sorted(body["data"], key=lambda item: item["index"])
        vectors: list[list[float]] = [item["embedding"] for item in data]
        if len(vectors) != len(texts) or any(len(v) != EMBEDDING_DIMENSIONS for v in vectors):
            raise EmbeddingError("Az embedding-szolgáltatás váratlan választ adott.")
        tokens = body.get("usage", {}).get("total_tokens")
        if tokens is not None:
            trace.get_current_span().set_attribute(gen_ai.GEN_AI_USAGE_INPUT_TOKENS, tokens)
        logger.info(
            "embedding call",
            model=self._model,
            texts=len(texts),
            tokens=tokens,
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
        return vectors

    def _retry_wait(self, response: httpx.Response, attempt: int) -> float | None:
        """Seconds to wait before the next attempt, or None: do not retry."""
        transient = response.status_code == 429 or response.status_code >= 500
        if not transient or attempt == self.MAX_RETRIES:
            return None
        try:
            wait = float(response.headers.get("retry-after", 2**attempt))
        except ValueError:  # an HTTP date instead of seconds
            wait = float(2**attempt)
        return wait if 0 <= wait <= self.MAX_WAIT_SECONDS else None

    async def close(self) -> None:
        await self._client.aclose()


class HashingEmbedder:
    """Feature hashing over words and character trigrams: no model, no network, deterministic.

    Lexical similarity only ("hitelek" and "hitelünk" share trigrams, synonyms share nothing), so
    it is no substitute for a real model. It keeps tests and the keyless demo meaningful: a
    question about loans still finds the loan examples.
    """

    model = f"hashing-v1-{EMBEDDING_DIMENSIONS}"

    async def embed(self, texts: Sequence[str], *, input_type: InputType) -> list[list[float]]:
        return [self.vector(text) for text in texts]

    @staticmethod
    def vector(text: str) -> list[float]:
        values = [0.0] * EMBEDDING_DIMENSIONS
        for feature, weight in _features(text):
            digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % EMBEDDING_DIMENSIONS
            sign = 1.0 if digest[4] & 1 else -1.0
            values[index] += sign * weight
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / norm for v in values]


def _features(text: str) -> list[tuple[str, float]]:
    words = re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold())
    features = [(f"w:{word}", 1.0) for word in words]
    for word in words:
        padded = f" {word} "
        features.extend((f"c:{padded[i : i + 3]}", 0.5) for i in range(len(padded) - 2))
    return features


def build_embedder(settings: Settings) -> Embedder | None:
    """None: no embedder configured (Voyage without a key), so dynamic few-shot stays off."""
    if settings.embedding_provider == "hashing":
        return HashingEmbedder()
    if settings.voyage_api_key is None:
        return None
    return VoyageEmbedder(settings)

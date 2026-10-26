"""Hybrid document search: vector similarity and Hungarian full-text search, fused with
Reciprocal Rank Fusion (docs/03-architektura.md, 3.).

The vector side finds the meaning ("mennyibe kerül" ~ "díja"), the full-text side the exact
terms (amounts, product names). The reading level is a WHERE condition in both queries: a
document above the user's level never leaves the database, whatever the question.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

import structlog
from sqlalchemy import Text, cast, func, literal_column, select, text
from sqlalchemy.dialects.postgresql import TSQUERY
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finql.llm.embeddings import Embedder, EmbeddingError
from finql.rag.models import Document, DocumentAccess, DocumentChunk

logger = structlog.get_logger(__name__)

# Candidates per side before fusion, and the RRF constant (60: the value of the original paper,
# it damps the weight of the very first ranks).
CANDIDATES = 40
RRF_K = 60

type SearchMode = Literal["hybrid", "text"]


@dataclass(frozen=True)
class SearchHit:
    chunk_id: int
    document_id: int
    source_path: str
    title: str
    doc_type: str
    access_level: DocumentAccess
    effective_from: date
    version: int
    chunk_index: int
    section: str
    content: str
    score: float  # the RRF score
    vector_rank: int | None  # 1-based rank on each side; None: not among its candidates
    text_rank: int | None

    @property
    def ref(self) -> str:
        """Stable reference for the log: file, document version, chunk."""
        return f"{self.source_path}@{self.version}#{self.chunk_index}"


@dataclass(frozen=True)
class SearchResult:
    hits: list[SearchHit]
    mode: SearchMode  # "text": no embedding (no embedder, or the service is down)


def fuse(rankings: Sequence[Sequence[int]], *, k: int = RRF_K) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion: score(d) = Σ 1 / (k + rank of d in each ranking). Only ranks
    count, not the raw scores, so a cosine distance and a ts_rank need no common scale. Ties
    break by id, so the order is deterministic."""
    scores: dict[int, float] = defaultdict(float)
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] += 1 / (k + rank)
    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))


class Retriever:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        embedder: Embedder | None,
        *,
        candidates: int = CANDIDATES,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._embedder = embedder
        self._candidates = candidates

    async def search(self, query: str, *, access: DocumentAccess, top_k: int) -> SearchResult:
        vector = await self._embed(query)
        async with self._sessionmaker() as session, session.begin():
            text_ids = await self._text_candidates(session, query, access)
            vector_ids = (
                await self._vector_candidates(session, vector, access) if vector is not None else []
            )
            fused = fuse([vector_ids, text_ids])[:top_k]
            hits = await self._load(session, fused, vector_ids, text_ids)
        return SearchResult(hits=hits, mode="hybrid" if vector is not None else "text")

    async def _embed(self, query: str) -> list[float] | None:
        """None: search on text only. An embedding outage costs the semantic half of the search,
        not the search."""
        if self._embedder is None:
            return None
        try:
            (vector,) = await self._embedder.embed([query], input_type="query")
        except EmbeddingError:
            logger.warning("document search on text only: embedding unavailable")
            return None
        return vector

    async def _vector_candidates(
        self, session: AsyncSession, vector: list[float], access: DocumentAccess
    ) -> list[int]:
        assert self._embedder is not None
        # A filtered HNSW scan may stop with fewer rows than the LIMIT; the iterative scan keeps
        # going until the filter has let enough through (pgvector 0.8).
        await session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
        distance = DocumentChunk.embedding.cosine_distance(vector)
        rows = await session.scalars(
            select(DocumentChunk.id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                Document.access_level <= access,
                DocumentChunk.embedding_model == self._embedder.model,
            )
            .order_by(distance, DocumentChunk.id)
            .limit(self._candidates)
        )
        return list(rows)

    async def _text_candidates(
        self, session: AsyncSession, query: str, access: DocumentAccess
    ) -> list[int]:
        # plainto_tsquery joins the words with AND: a question of eight words would only match a
        # chunk that has all eight. With OR, the rank decides: more (and heading) matches first.
        # The stemmed lexemes are re-parsed as a tsquery, so no user text reaches the parser.
        and_query = func.plainto_tsquery(literal_column("'hungarian'"), query)
        or_query = cast(func.replace(cast(and_query, Text), " & ", " | "), TSQUERY)
        rank = func.ts_rank_cd(DocumentChunk.tsv, or_query)
        rows = await session.scalars(
            select(DocumentChunk.id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(Document.access_level <= access, DocumentChunk.tsv.bool_op("@@")(or_query))
            .order_by(rank.desc(), DocumentChunk.id)
            .limit(self._candidates)
        )
        return list(rows)

    async def _load(
        self,
        session: AsyncSession,
        fused: Sequence[tuple[int, float]],
        vector_ids: Sequence[int],
        text_ids: Sequence[int],
    ) -> list[SearchHit]:
        if not fused:
            return []
        rows = {
            row.DocumentChunk.id: row
            for row in await session.execute(
                select(DocumentChunk, Document)
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(DocumentChunk.id.in_([chunk_id for chunk_id, _ in fused]))
            )
        }
        vector_rank = {chunk_id: rank for rank, chunk_id in enumerate(vector_ids, start=1)}
        text_rank = {chunk_id: rank for rank, chunk_id in enumerate(text_ids, start=1)}
        hits = []
        for chunk_id, score in fused:
            chunk, document = rows[chunk_id].DocumentChunk, rows[chunk_id].Document
            hits.append(
                SearchHit(
                    chunk_id=chunk.id,
                    document_id=document.id,
                    source_path=document.source_path,
                    title=document.title,
                    doc_type=document.doc_type,
                    access_level=document.access_level,
                    effective_from=document.effective_from,
                    version=document.version,
                    chunk_index=chunk.chunk_index,
                    section=chunk.section,
                    content=chunk.content,
                    score=score,
                    vector_rank=vector_rank.get(chunk_id),
                    text_rank=text_rank.get(chunk_id),
                )
            )
        return hits

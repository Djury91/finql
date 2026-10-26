"""`finql ingest`: the documents directory → app.documents and app.document_chunks.

Incremental: a document whose content hash and embedding model are unchanged is skipped, a
changed one is re-chunked and re-embedded as a whole, and a document whose file is gone is
deleted with its chunks. One transaction: a failure (an embedding outage halfway) leaves the
previous state intact.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finql.llm.embeddings import Embedder
from finql.rag.chunking import Chunk, chunk_document
from finql.rag.models import Document, DocumentChunk
from finql.rag.sources import DocumentError, SourceDocument


@dataclass
class IngestResult:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    chunks: int = 0  # chunks written in this run


def embedding_text(title: str, chunk: Chunk) -> str:
    """What gets embedded: the chunk with its title and section, so "Késedelem" in the personal
    loan terms is about personal loans."""
    heading = f"{title}\n{chunk.section}" if chunk.section else title
    return f"{heading}\n\n{chunk.content}"


async def ingest_documents(
    sessionmaker: async_sessionmaker[AsyncSession],
    embedder: Embedder,
    documents: Sequence[SourceDocument],
    *,
    force: bool = False,
    progress: Callable[[str, str], None] | None = None,
) -> IngestResult:
    """`documents`: the whole directory (sources.load_documents). `force`: re-process every
    document, e.g. after a chunking change."""
    if not documents:
        # An empty or wrong directory would otherwise delete every document.
        raise DocumentError("nincs betölthető dokumentum")
    report = progress or (lambda _path, _status: None)
    result = IngestResult()
    async with sessionmaker() as session, session.begin():
        existing = {doc.source_path: doc for doc in await session.scalars(select(Document))}
        stale_models = set(
            await session.scalars(
                select(DocumentChunk.document_id)
                .where(DocumentChunk.embedding_model != embedder.model)
                .distinct()
            )
        )
        for source in documents:
            row = existing.get(source.source_path)
            if (
                row is not None
                and not force
                and row.content_hash == source.content_hash
                and row.id not in stale_models
            ):
                result.unchanged.append(source.source_path)
                report(source.source_path, "változatlan")
                continue
            if row is None:
                row = Document(source_path=source.source_path, version=1)
                session.add(row)
                result.added.append(source.source_path)
                status = "új"
            else:
                if row.content_hash != source.content_hash:
                    row.version += 1
                await session.execute(
                    delete(DocumentChunk).where(DocumentChunk.document_id == row.id)
                )
                result.updated.append(source.source_path)
                status = "frissítve"
            _apply_meta(row, source)
            await session.flush()  # the id of a new document
            written = await _write_chunks(session, embedder, row, source)
            result.chunks += written
            report(source.source_path, f"{status} ({written} részlet)")

        wanted = {source.source_path for source in documents}
        for path, row in existing.items():
            if path not in wanted:
                await session.delete(row)  # the chunks go with it (ON DELETE CASCADE)
                result.deleted.append(path)
                report(path, "törölve")
    return result


def _apply_meta(row: Document, source: SourceDocument) -> None:
    row.title = source.meta.title
    row.doc_type = source.meta.doc_type
    row.access_level = source.meta.access_level
    row.effective_from = source.meta.effective_from
    row.content_hash = source.content_hash
    row.ingested_at = datetime.now(UTC)


async def _write_chunks(
    session: AsyncSession, embedder: Embedder, row: Document, source: SourceDocument
) -> int:
    chunks = chunk_document(source.body)
    vectors = await embedder.embed(
        [embedding_text(source.meta.title, chunk) for chunk in chunks], input_type="document"
    )
    session.add_all(
        DocumentChunk(
            document_id=row.id,
            chunk_index=chunk.index,
            section=chunk.section,
            content=chunk.content,
            token_count=chunk.token_count,
            embedding=vector,
            embedding_model=embedder.model,
        )
        for chunk, vector in zip(chunks, vectors, strict=True)
    )
    return len(chunks)

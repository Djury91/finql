import enum
import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    BigInteger,
    Computed,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from finql.audit.models import HashChained
from finql.auth.models import UserRole
from finql.core.base_model import Base
from finql.llm.embeddings import EMBEDDING_DIMENSIONS


class DocumentAccess(enum.StrEnum):
    """Who may read a document. Declaration order is the database enum's sort order, so
    `access_level <= :level` is the filter."""

    GENERAL = "general"  # every employee
    INTERNAL = "internal"  # central functions: not for branch staff

    def covers(self, level: "DocumentAccess") -> bool:
        """A reader at this level may read a document at `level`. By declaration order, not by
        the string values."""
        order = list(DocumentAccess)
        return order.index(level) <= order.index(self)


# The roles are not a ladder (an auditor sees no bank data, yet reads every policy), so the
# reading level is a mapping, not a rank of the role.
ROLE_ACCESS = {
    UserRole.BRANCH_MANAGER: DocumentAccess.GENERAL,
    UserRole.ANALYST: DocumentAccess.INTERNAL,
    UserRole.AUDITOR: DocumentAccess.INTERNAL,
    UserRole.ADMIN: DocumentAccess.INTERNAL,
}


def _enum_values(enum_type: type[enum.Enum]) -> list[str]:
    return [member.value for member in enum_type]


# One type object for both columns that use it, so Alembic creates the type once.
DOCUMENT_ACCESS_TYPE = Enum(DocumentAccess, name="document_access", values_callable=_enum_values)


class Document(Base):
    """A source document (data/documents/*.md). Loaded by `finql ingest`: a changed content
    hash means re-chunking and re-embedding."""

    __tablename__ = "documents"
    __table_args__ = ({"comment": "RAG-dokumentumok: szabályzatok, díjjegyzékek, hirdetmények."},)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    # Relative to the documents directory, e.g. "hirdetmeny-kamatok.md".
    source_path: Mapped[str] = mapped_column(Text, unique=True)
    title: Mapped[str] = mapped_column(Text)
    doc_type: Mapped[str] = mapped_column(Text)
    access_level: Mapped[DocumentAccess] = mapped_column(DOCUMENT_ACCESS_TYPE)
    effective_from: Mapped[date] = mapped_column(Date)
    # SHA-256 of the file text with LF line endings: the same on every checkout.
    content_hash: Mapped[str] = mapped_column(Text)
    # 1 on the first ingest, +1 on every content change.
    version: Mapped[int] = mapped_column(server_default=text("1"))
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DocumentChunk(Base):
    """A section (or part of a long section) of a document, with its vector and its full-text
    index. Rewritten as a whole when the document changes."""

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index"),
        Index(
            None,
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index(None, "tsv", postgresql_using="gin"),
        {"comment": "Dokumentumrészletek embeddinggel és magyar teljes szöveges indexszel."},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("app.documents.id", ondelete="CASCADE"))
    chunk_index: Mapped[int] = mapped_column(Integer)
    # The heading path within the document ("Késedelem", "Díjak > Kártyák"); empty for the text
    # before the first heading. The answer cites it.
    section: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)  # an estimate (rag/chunking.py)
    embedding: Mapped[list[float]] = mapped_column(VECTOR(EMBEDDING_DIMENSIONS))
    embedding_model: Mapped[str] = mapped_column(Text)
    # Hungarian stemming ("kamatot" finds "kamat"); a match in the heading weighs more.
    tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('hungarian', section), 'A') || "
            "setweight(to_tsvector('hungarian', content), 'B')",
            persisted=True,
        ),
    )


class AnswerStatus(enum.StrEnum):
    OK = "ok"  # a cited answer
    NO_ANSWER = "no_answer"  # nothing found, or the sources do not answer the question
    UNCITED = "uncited"  # the model answered without a valid citation: not shown
    REJECTED_BUDGET = "rejected_budget"
    LLM_ERROR = "llm_error"


class AnswerLog(HashChained, Base):
    """Every document answer: what was retrieved, what was cited, what it cost. Append-only and
    hash-chained like the query log (db/app/020_answer_log.sql), and counted in the daily token
    budget."""

    __tablename__ = "answer_log"
    __table_args__ = (
        Index(None, "user_id", "created_at"),
        Index(None, "created_at"),
        Index(None, "chain_seq", unique=True),
        {"comment": "Dokumentum-válaszok naplója: források, idézetek, tokenek. Csak hozzáfűzhető."},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app.users.id"))
    question: Mapped[str] = mapped_column(Text)
    status: Mapped[AnswerStatus] = mapped_column(
        Enum(AnswerStatus, name="answer_status", values_callable=_enum_values)
    )
    # The reading level the search ran with, as it was at that moment.
    access_level: Mapped[DocumentAccess] = mapped_column(DOCUMENT_ACCESS_TYPE)
    search_mode: Mapped[str | None] = mapped_column(Text)  # hybrid, or text when no embedding
    # The chunks in the prompt, in order, and the ones the answer cites, as
    # "file@version#chunk" (e.g. "hirdetmeny-kamatok.md@2#3"). Not chunk ids: a re-ingest
    # replaces the chunks, while the version still says which text the answer was based on.
    source_refs: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    cited_refs: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    answer: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(server_default=text("0"))
    llm_latency_ms: Mapped[int | None]
    request_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

from datetime import datetime

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import DateTime, Identity, Text, func, text, true
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from finql.core.base_model import Base
from finql.llm.embeddings import EMBEDDING_DIMENSIONS


class SqlExample(Base):
    """A curated question–SQL pair. The most similar ones go into the prompt (dynamic few-shot).

    The source is data/sql_examples.yaml, loaded with `finql examples sync`. No vector index: a
    few dozen rows are scanned faster than an index is searched.
    """

    __tablename__ = "sql_examples"
    __table_args__ = ({"comment": "Few-shot példák: kérdés–SQL párok embeddinggel."},)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    question: Mapped[str] = mapped_column(Text, unique=True)
    sql: Mapped[str] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    embedding: Mapped[list[float]] = mapped_column(VECTOR(EMBEDDING_DIMENSIONS))
    # Only vectors of the current model are compared; a model change means re-embedding.
    embedding_model: Mapped[str] = mapped_column(Text)
    # Removed from the source file: kept for the query log's references, never selected.
    is_active: Mapped[bool] = mapped_column(server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

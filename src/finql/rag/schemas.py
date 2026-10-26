from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from finql.rag.answer import DocumentAnswer
from finql.rag.models import DocumentAccess
from finql.rag.retriever import SearchHit, SearchMode, SearchResult


class SearchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500, examples=["késedelmi kamat személyi kölcsön"])
    top_k: int = Field(default=5, ge=1, le=20)


class SearchHitOut(BaseModel):
    chunk_id: int
    document_id: int
    source_path: str
    title: str
    doc_type: str
    access_level: DocumentAccess
    effective_from: date
    section: str
    content: str
    score: float  # Reciprocal Rank Fusion score
    vector_rank: int | None  # rank on each side of the hybrid search; None: not a candidate
    text_rank: int | None

    @classmethod
    def from_hit(cls, hit: SearchHit) -> "SearchHitOut":
        return cls(
            chunk_id=hit.chunk_id,
            document_id=hit.document_id,
            source_path=hit.source_path,
            title=hit.title,
            doc_type=hit.doc_type,
            access_level=hit.access_level,
            effective_from=hit.effective_from,
            section=hit.section,
            content=hit.content,
            score=hit.score,
            vector_rank=hit.vector_rank,
            text_rank=hit.text_rank,
        )


class SearchResponse(BaseModel):
    mode: SearchMode  # "text": the embedding service was not available
    results: list[SearchHitOut]

    @classmethod
    def from_result(cls, result: SearchResult) -> "SearchResponse":
        return cls(mode=result.mode, results=[SearchHitOut.from_hit(hit) for hit in result.hits])


class AnswerRequest(BaseModel):
    question: str = Field(
        min_length=3, max_length=1000, examples=["Mennyi a késedelmi kamat a személyi kölcsönnél?"]
    )


class SourceOut(BaseModel):
    number: int  # the [n] in the answer
    cited: bool
    document_id: int
    source_path: str
    title: str
    section: str
    effective_from: date
    content: str


class AnswerResponse(BaseModel):
    answer_id: int  # the answer_log row
    status: Literal["ok", "no_answer"]  # no_answer: the documents do not answer the question
    answer: str
    citations: list[int]  # source numbers the answer cites
    sources: list[SourceOut]
    search_mode: SearchMode | None

    @classmethod
    def from_answer(cls, answer: DocumentAnswer) -> "AnswerResponse":
        return cls(
            answer_id=answer.log_id,
            status=answer.status,
            answer=answer.answer,
            citations=answer.cited,
            sources=[
                SourceOut(
                    number=number,
                    cited=number in answer.cited,
                    document_id=hit.document_id,
                    source_path=hit.source_path,
                    title=hit.title,
                    section=hit.section,
                    effective_from=hit.effective_from,
                    content=hit.content,
                )
                for number, hit in enumerate(answer.sources, start=1)
            ],
            search_mode=answer.search_mode,
        )

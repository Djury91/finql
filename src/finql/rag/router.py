from typing import Any

from fastapi import APIRouter, Request

from finql.auth.dependencies import CurrentUser
from finql.core.deps import AppSettings, DbSession
from finql.core.errors import FORBIDDEN, UNAUTHORIZED, ErrorResponse
from finql.core.logging import current_request_id
from finql.rag import answer as answer_service
from finql.rag.answer import RagPipeline, document_access
from finql.rag.retriever import Retriever
from finql.rag.schemas import AnswerRequest, AnswerResponse, SearchRequest, SearchResponse

router = APIRouter(prefix="/documents", tags=["documents"])

ANSWER_ERRORS: dict[int | str, dict[str, Any]] = {
    422: {"model": ErrorResponse, "description": "A nyelvi modell elutasította a kérést"},
    429: {"model": ErrorResponse, "description": "Elfogyott a napi tokenkeret"},
    503: {"model": ErrorResponse, "description": "A nyelvi modell nem érhető el"},
}


@router.post("/search", responses={**UNAUTHORIZED, **FORBIDDEN})
async def search(body: SearchRequest, request: Request, user: CurrentUser) -> SearchResponse:
    """Hibrid keresés (vektoros + magyar teljes szöveges) a szabályzatokban. Csak a
    szerepkörödnek megfelelő dokumentumokban keres; a belsőket a fiókvezető nem látja."""
    retriever: Retriever = request.app.state.retriever
    result = await retriever.search(body.query, access=document_access(user), top_k=body.top_k)
    return SearchResponse.from_result(result)


@router.post("/answer", responses={**UNAUTHORIZED, **FORBIDDEN, **ANSWER_ERRORS})
async def answer(
    body: AnswerRequest,
    request: Request,
    session: DbSession,
    settings: AppSettings,
    user: CurrentUser,
) -> AnswerResponse:
    """Válasz a dokumentumokból, forrásmegjelöléssel: a válasz minden állítása mögött ott a
    forrás száma, a források a válaszban. Forrás nélküli választ nem ad."""
    pipeline = RagPipeline(
        llm=request.app.state.rag_llm_client,
        retriever=request.app.state.retriever,
        log_sessionmaker=request.app.state.sessionmaker,
        top_k=settings.rag_top_k,
    )
    result = await answer_service.answer_question(
        pipeline, session, user, body.question, request_id=current_request_id()
    )
    return AnswerResponse.from_answer(result)

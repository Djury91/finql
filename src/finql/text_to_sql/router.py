from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request

from finql.audit import service as audit_service
from finql.audit.schemas import QueryLogOut
from finql.auth.dependencies import CurrentUser, require_role
from finql.auth.models import User, UserRole
from finql.core.deps import AppSettings, DbSession
from finql.core.errors import FORBIDDEN, UNAUTHORIZED, AppError, ErrorResponse
from finql.core.logging import current_request_id
from finql.text_to_sql import service
from finql.text_to_sql.schema_context import CatalogCache, SchemaCatalog
from finql.text_to_sql.schemas import QueryRequest, QueryResponse

router = APIRouter(tags=["text-to-sql"])

REJECTED: dict[int | str, dict[str, Any]] = {
    422: {
        "model": ErrorResponse,
        "description": "Elutasított vagy hibás lekérdezés (sql_rejected, query_too_expensive, "
        "query_timeout, sql_error, llm_refused); a details a naplóazonosítót és az SQL-t adja",
    },
    429: {"model": ErrorResponse, "description": "Elfogyott a napi tokenkeret"},
    503: {"model": ErrorResponse, "description": "A nyelvi modell vagy az adatbázis nem érhető el"},
}


class NotConfiguredError(AppError):
    status_code = 503
    code = "not_configured"
    message = "A text-to-SQL nincs beállítva (FINQL_LLM_DATABASE_URL)."


async def get_catalog(request: Request) -> SchemaCatalog:
    engine = request.app.state.llm_engine
    if engine is None:
        raise NotConfiguredError()
    cache: CatalogCache = request.app.state.catalog_cache
    return await cache.get(engine)


Catalog = Annotated[SchemaCatalog, Depends(get_catalog)]


@router.post("/query", responses={**UNAUTHORIZED, **FORBIDDEN, **REJECTED})
async def query(
    body: QueryRequest,
    request: Request,
    session: DbSession,
    settings: AppSettings,
    catalog: Catalog,
    user: Annotated[
        User, Depends(require_role(UserRole.BRANCH_MANAGER, UserRole.ANALYST, UserRole.ADMIN))
    ],
) -> QueryResponse:
    """Kérdés magyarul → ellenőrzött SQL → eredmény. A fiókvezető csak a saját fiókja adatait
    látja. Minden kísérlet a lekérdezésnaplóba kerül, az elutasítottak is."""
    pipeline = service.Pipeline(
        llm=request.app.state.llm_client,
        catalog=catalog,
        llm_engine=request.app.state.llm_engine,
        log_sessionmaker=request.app.state.sessionmaker,
        settings=settings,
    )
    answer = await service.answer_question(
        pipeline, session, user, body.question, request_id=current_request_id()
    )
    return QueryResponse.from_answer(answer)


@router.get("/query/history", responses=UNAUTHORIZED)
async def history(
    session: DbSession,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[QueryLogOut]:
    """A saját korábbi kérdéseim, kísérletenként, a legfrissebb elöl."""
    rows = await audit_service.list_queries(session, user_id=user.id, limit=limit, offset=offset)
    return [QueryLogOut.model_validate(row) for row in rows]


@router.get("/schema", responses=UNAUTHORIZED)
async def schema(_: CurrentUser, catalog: Catalog) -> SchemaCatalog:
    """Az LLM által látott nézetek és oszlopok, leírással (átláthatóság)."""
    return catalog

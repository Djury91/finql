import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from finql.audit import service
from finql.audit.models import QueryStatus
from finql.audit.schemas import QueryLogOut
from finql.auth.dependencies import require_role
from finql.auth.models import User, UserRole
from finql.core.deps import DbSession
from finql.core.errors import FORBIDDEN, UNAUTHORIZED

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/queries", responses={**UNAUTHORIZED, **FORBIDDEN})
async def queries(
    session: DbSession,
    _: Annotated[User, Depends(require_role(UserRole.AUDITOR, UserRole.ADMIN))],
    user_id: uuid.UUID | None = None,
    status: QueryStatus | None = None,
    since: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[QueryLogOut]:
    """Lekérdezésnapló: minden kísérlet, az elutasítottak is (auditor és admin)."""
    rows = await service.list_queries(
        session, user_id=user_id, status=status, since=since, limit=limit, offset=offset
    )
    return [QueryLogOut.model_validate(row) for row in rows]

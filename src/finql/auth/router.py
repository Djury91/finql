from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm

from finql.auth import service
from finql.auth.dependencies import CurrentUser, require_role
from finql.auth.models import User, UserRole
from finql.auth.schemas import TokenResponse, UserOut
from finql.core.deps import AppSettings, DbSession
from finql.core.errors import ErrorResponse

router = APIRouter(prefix="/auth", tags=["auth"])

UNAUTHORIZED: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Nincs vagy érvénytelen a token"}
}
FORBIDDEN: dict[int | str, dict[str, Any]] = {
    403: {"model": ErrorResponse, "description": "Nincs jogosultság"}
}


@router.post("/token", responses=UNAUTHORIZED)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: DbSession,
    settings: AppSettings,
) -> TokenResponse:
    """Bejelentkezés e-mail-címmel (a `username` mezőben) és jelszóval. A /docs „Authorize”
    gombja is ezt hívja."""
    user = await service.authenticate(session, form.username, form.password)
    return service.issue_token(user, settings)


@router.get("/me", responses=UNAUTHORIZED)
async def me(user: CurrentUser) -> UserOut:
    """A bejelentkezett felhasználó adatai és szerepköre."""
    return UserOut.model_validate(user)


@router.get("/users", responses={**UNAUTHORIZED, **FORBIDDEN})
async def users(
    session: DbSession,
    _: Annotated[User, Depends(require_role(UserRole.ADMIN))],
) -> list[UserOut]:
    """Felhasználók listája (csak admin)."""
    return [UserOut.model_validate(user) for user in await service.list_users(session)]

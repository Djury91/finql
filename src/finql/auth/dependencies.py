from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

from finql.auth import service
from finql.auth.models import User, UserRole
from finql.core.deps import AppSettings, DbSession
from finql.core.errors import NotAuthenticatedError, PermissionDeniedError
from finql.core.security import decode_access_token

# auto_error=False: a missing token goes through our error format, not FastAPI's default.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)


async def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    session: DbSession,
    settings: AppSettings,
) -> User:
    if not token:
        raise NotAuthenticatedError()
    claims = decode_access_token(
        token, secret=settings.jwt_secret.get_secret_value(), issuer=settings.jwt_issuer
    )
    return await service.get_active_user(session, claims.user_id)


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*roles: UserRole) -> Callable[[User], Awaitable[User]]:
    """Dependency factory: `Depends(require_role(UserRole.ADMIN))`. The role comes from the
    database, not from the token, so a role change applies immediately."""

    async def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise PermissionDeniedError()
        return user

    return checker

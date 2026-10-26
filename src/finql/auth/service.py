import uuid
from collections.abc import Sequence
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from finql.auth.models import User, UserRole
from finql.auth.schemas import TokenResponse
from finql.core.config import Settings
from finql.core.errors import ConflictError, NotAuthenticatedError
from finql.core.security import (
    create_access_token,
    dummy_hash,
    hash_password,
    needs_rehash,
    verify_password,
)

LOGIN_FAILED = "Hibás e-mail-cím vagy jelszó."


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def authenticate(session: AsyncSession, email: str, password: str) -> User:
    """The same error, and about the same time, for an unknown user, a wrong password and an
    inactive account: the response must not tell which e-mail addresses exist."""
    user = await session.scalar(select(User).where(User.email == normalize_email(email)))
    # Argon2 takes tens of milliseconds of CPU: off the event loop, so other requests keep going.
    if user is None:
        await run_in_threadpool(verify_password, dummy_hash(), password)
        raise NotAuthenticatedError(LOGIN_FAILED)
    if not await run_in_threadpool(verify_password, user.password_hash, password):
        raise NotAuthenticatedError(LOGIN_FAILED)
    if not user.is_active:
        raise NotAuthenticatedError(LOGIN_FAILED)
    if needs_rehash(user.password_hash):
        user.password_hash = await run_in_threadpool(hash_password, password)
    return user


def issue_token(user: User, settings: Settings) -> TokenResponse:
    ttl = timedelta(minutes=settings.access_token_ttl_minutes)
    token = create_access_token(
        user_id=user.id,
        role=user.role.value,
        branch_id=user.branch_id,
        secret=settings.jwt_secret.get_secret_value(),
        issuer=settings.jwt_issuer,
        ttl=ttl,
    )
    return TokenResponse(access_token=token, expires_in=int(ttl.total_seconds()))


async def get_active_user(session: AsyncSession, user_id: uuid.UUID) -> User:
    """Looked up on every request: a deactivated user or changed role takes effect at once,
    not only when the token expires."""
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise NotAuthenticatedError("A felhasználó nem létezik vagy le van tiltva.")
    return user


async def create_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    full_name: str,
    role: UserRole,
    branch_id: int | None = None,
) -> User:
    user = User(
        email=normalize_email(email),
        password_hash=await run_in_threadpool(hash_password, password),
        full_name=full_name,
        role=role,
        branch_id=branch_id,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError(
            f"Már létezik felhasználó ezzel az e-mail-címmel: {user.email}"
        ) from exc
    return user


async def list_users(session: AsyncSession) -> Sequence[User]:
    return (await session.scalars(select(User).order_by(User.email))).all()

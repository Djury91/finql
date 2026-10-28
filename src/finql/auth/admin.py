"""User administration from the CLI. Runs with the migration connection (finql_migrator):
it resolves branch codes in the bank schema, which the application role cannot read."""

from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from finql.auth import service
from finql.auth.models import User, UserRole
from finql.core.db import async_url, create_sessionmaker
from finql.core.errors import AppError
from finql.core.security import hash_password, verify_password


@dataclass(frozen=True)
class NewUser:
    email: str
    full_name: str
    role: UserRole
    branch_code: str | None = None


DEMO_DOMAIN = "minta-bank.example"  # .example is reserved (RFC 2606), it never reaches anyone
DEMO_USERS = (
    NewUser(f"admin@{DEMO_DOMAIN}", "Admin Anna", UserRole.ADMIN),
    NewUser(f"elemzo@{DEMO_DOMAIN}", "Elemző Endre", UserRole.ANALYST),
    NewUser(f"auditor@{DEMO_DOMAIN}", "Auditor Aliz", UserRole.AUDITOR),
    NewUser(f"pecs@{DEMO_DOMAIN}", "Pécsi Péter", UserRole.BRANCH_MANAGER, "PEC01"),
    NewUser(f"budaors@{DEMO_DOMAIN}", "Budaörsi Bea", UserRole.BRANCH_MANAGER, "BUO01"),
)


class AdminError(AppError):
    code = "admin_error"


async def _branch_id(session: AsyncSession, code: str | None) -> int | None:
    if code is None:
        return None
    branch_id = await session.scalar(
        text("SELECT branch_id FROM bank.branches WHERE code = :code"), {"code": code.upper()}
    )
    if branch_id is None:
        raise AdminError(f"Nincs ilyen fiók: {code}")
    return int(branch_id)


async def create_users(database_url: str, users: list[NewUser], password: str) -> list[str]:
    """Create the users that do not exist yet. Returns the e-mail addresses actually created."""
    engine = create_async_engine(async_url(database_url))
    created: list[str] = []
    try:
        async with create_sessionmaker(engine)() as session, session.begin():
            for new in users:
                email = service.normalize_email(new.email)
                if await session.scalar(select(User.id).where(User.email == email)):
                    continue
                if (new.role == UserRole.BRANCH_MANAGER) != (new.branch_code is not None):
                    raise AdminError("Fiókkód (--branch) csak és kötelezően fiókvezetőnek kell.")
                await service.create_user(
                    session,
                    email=email,
                    password=password,
                    full_name=new.full_name,
                    role=new.role,
                    branch_id=await _branch_id(session, new.branch_code),
                )
                created.append(email)
    finally:
        await engine.dispose()
    return created


async def sync_demo_users(database_url: str, password: str) -> dict[str, str]:
    """The demo users with this password: the missing ones are created, the existing ones get
    the password if theirs differs. `setup` runs it at every deploy, so changing
    FINQL_DEMO_PASSWORD changes the password too, and an old, public one stops working (e.g.
    before switching a public demo to a real API key). Other users are never touched.
    Returns the status per e-mail address."""
    created = set(await create_users(database_url, list(DEMO_USERS), password))
    status: dict[str, str] = {}
    engine = create_async_engine(async_url(database_url))
    try:
        async with create_sessionmaker(engine)() as session, session.begin():
            for demo in DEMO_USERS:
                email = service.normalize_email(demo.email)
                if email in created:
                    status[email] = "létrehozva"
                    continue
                user = await session.scalar(select(User).where(User.email == email))
                if user is None:  # deleted since create_users: nothing to sync
                    continue
                if verify_password(user.password_hash, password):
                    status[email] = "változatlan"
                else:
                    user.password_hash = hash_password(password)
                    status[email] = "jelszó frissítve"
    finally:
        await engine.dispose()
    return status

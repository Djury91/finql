"""Login, tokens and roles against a real database, with the application's own role (finql_app)."""

import asyncio
import dataclasses
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from alembic import command
from fastapi.testclient import TestClient

from finql.auth.admin import DEMO_USERS, NewUser, create_users, sync_demo_users
from finql.auth.models import UserRole
from finql.core.db import async_url
from finql.core.security import create_access_token
from finql.main import create_app
from finql.pipelines.seed.loader import SeedError, load
from finql.pipelines.seed.scales import SCALES
from tests.helpers import TEST_JWT_SECRET, make_settings

from .api import ADMIN, ANALYST, PASSWORD, PECS_MANAGER, bearer, login
from .db import DbUrls, alembic_config

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client(seeded_db: DbUrls) -> Iterator[TestClient]:
    asyncio.run(create_users(seeded_db.migrator, list(DEMO_USERS), PASSWORD))
    app = create_app(make_settings(async_url(seeded_db.app)))
    with TestClient(app) as test_client:
        yield test_client


def set_active(urls: DbUrls, email: str, active: bool) -> None:
    with psycopg.connect(urls.conninfo("migrator")) as conn:
        conn.execute("UPDATE app.users SET is_active = %s WHERE email = %s", (active, email))


def test_login_and_me_return_role_and_branch(client: TestClient, seeded_db: DbUrls) -> None:
    token = login(client, PECS_MANAGER)
    response = client.get("/auth/me", headers=bearer(token))
    with psycopg.connect(seeded_db.conninfo("migrator")) as conn:
        pecs = conn.execute("SELECT branch_id FROM bank.branches WHERE code = 'PEC01'").fetchone()

    assert response.status_code == 200
    me = response.json()
    assert (me["email"], me["role"]) == (PECS_MANAGER, "branch_manager")
    assert pecs is not None and me["branch_id"] == pecs[0]
    assert "password_hash" not in me


def test_email_is_case_insensitive(client: TestClient) -> None:
    assert login(client, "  Elemzo@Minta-Bank.EXAMPLE ")


@pytest.mark.parametrize(
    ("email", "password"),
    [(ANALYST, "wrong-password"), ("nobody@minta-bank.example", PASSWORD)],
    ids=["wrong-password", "unknown-user"],
)
def test_failed_login_does_not_reveal_which_part_was_wrong(
    client: TestClient, email: str, password: str
) -> None:
    response = client.post("/auth/token", data={"username": email, "password": password})

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Hibás e-mail-cím vagy jelszó."
    assert response.headers["www-authenticate"] == "Bearer"


def test_admin_endpoint_requires_admin_role(client: TestClient) -> None:
    as_analyst = client.get("/auth/users", headers=bearer(login(client, ANALYST)))
    as_admin = client.get("/auth/users", headers=bearer(login(client, ADMIN)))

    assert as_analyst.status_code == 403
    assert as_analyst.json()["error"]["code"] == "forbidden"
    assert as_admin.status_code == 200
    assert {user["email"] for user in as_admin.json()} >= {u.email for u in DEMO_USERS}


def test_missing_token_is_401(client: TestClient) -> None:
    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


def test_expired_token_is_401(client: TestClient) -> None:
    me = client.get("/auth/me", headers=bearer(login(client, ANALYST))).json()
    expired = create_access_token(
        user_id=uuid.UUID(me["id"]),
        role=me["role"],
        branch_id=None,
        secret=TEST_JWT_SECRET,
        issuer="finql",
        ttl=timedelta(minutes=30),
        now=datetime.now(UTC) - timedelta(hours=1),
    )

    assert client.get("/auth/me", headers=bearer(expired)).status_code == 401


def test_token_of_an_unknown_user_is_401(client: TestClient) -> None:
    forged = create_access_token(
        user_id=uuid.uuid4(),
        role="admin",
        branch_id=None,
        secret=TEST_JWT_SECRET,
        issuer="finql",
        ttl=timedelta(minutes=5),
    )

    assert client.get("/auth/users", headers=bearer(forged)).status_code == 401


def test_deactivation_takes_effect_before_the_token_expires(
    client: TestClient, seeded_db: DbUrls
) -> None:
    email = "auditor@minta-bank.example"
    token = login(client, email)
    set_active(seeded_db, email, active=False)
    try:
        assert client.get("/auth/me", headers=bearer(token)).status_code == 401
        response = client.post("/auth/token", data={"username": email, "password": PASSWORD})
        assert response.status_code == 401
    finally:
        set_active(seeded_db, email, active=True)


def test_branch_manager_needs_a_branch(seeded_db: DbUrls) -> None:
    with (
        psycopg.connect(seeded_db.conninfo("app")) as conn,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        conn.execute(
            """INSERT INTO app.users (email, password_hash, full_name, role)
               VALUES ('x@minta-bank.example', 'h', 'X', 'branch_manager')"""
        )


def test_users_are_unique_regardless_of_case(seeded_db: DbUrls) -> None:
    created = asyncio.run(
        create_users(
            seeded_db.migrator,
            [NewUser(ADMIN.upper(), "Másik Admin", UserRole.ADMIN)],
            PASSWORD,
        )
    )

    assert created == []


def test_seed_reset_keeps_users_and_refuses_to_drop_their_branch(
    client: TestClient, seeded_db: DbUrls
) -> None:
    # Users reference bank.branches: a reload must not wipe them...
    load(seeded_db.conninfo("migrator"), SCALES["tiny"], seed=42, reset=True)
    assert login(client, PECS_MANAGER)

    # ...and must not silently drop a branch someone still belongs to.
    with psycopg.connect(seeded_db.conninfo("migrator")) as conn:
        conn.execute("UPDATE app.users SET branch_id = 6 WHERE email = %s", (PECS_MANAGER,))
    smaller = dataclasses.replace(SCALES["tiny"], branches=5)
    try:
        with pytest.raises(SeedError, match="fiókra hivatkozik"):
            load(seeded_db.conninfo("migrator"), smaller, seed=42, reset=True)
    finally:
        with psycopg.connect(seeded_db.conninfo("migrator")) as conn:
            conn.execute(
                """UPDATE app.users SET branch_id =
                       (SELECT branch_id FROM bank.branches WHERE code = 'PEC01')
                   WHERE email = %s""",
                (PECS_MANAGER,),
            )


def test_models_and_migrations_are_in_sync(migrated_db: DbUrls) -> None:
    # Fails if a model changed without a migration (autogenerate would find a difference).
    command.check(alembic_config(migrated_db.migrator))


def test_changing_the_demo_password_retires_the_old_one(
    client: TestClient, seeded_db: DbUrls
) -> None:
    # A public demo shows its password; before a real API key goes in, it must stop working.
    other = "kulso@minta-bank.example"
    asyncio.run(
        create_users(seeded_db.migrator, [NewUser(other, "Külső", UserRole.ANALYST)], PASSWORD)
    )
    try:
        status = asyncio.run(sync_demo_users(seeded_db.migrator, "Uj-interju-jelszo-1"))

        assert set(status.values()) == {"jelszó frissítve"}
        assert len(status) == len(DEMO_USERS)
        old = client.post("/auth/token", data={"username": PECS_MANAGER, "password": PASSWORD})
        assert old.status_code == 401
        assert login(client, PECS_MANAGER, "Uj-interju-jelszo-1")
        assert login(client, other)  # not a demo user: untouched

        again = asyncio.run(sync_demo_users(seeded_db.migrator, "Uj-interju-jelszo-1"))
        assert set(again.values()) == {"változatlan"}
    finally:
        asyncio.run(sync_demo_users(seeded_db.migrator, PASSWORD))

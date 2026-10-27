"""The hash-chained logs (db/app/040_log_chain.sql): built by the database, broken by tampering.

The database is shared by the whole test session, so tampering happens in transactions that are
rolled back: the chain stays intact for the other tests.
"""

import asyncio
import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from typer.testing import CliRunner

from finql import cli
from finql.audit.service import anchor_mismatch
from finql.auth.admin import DEMO_USERS, NewUser, create_users
from finql.auth.models import UserRole
from finql.core.db import async_url
from finql.main import create_app
from tests.helpers import make_settings

from .api import ANALYST, AUDITOR, PASSWORD, bearer, login
from .db import DbUrls

pytestmark = pytest.mark.integration

WRITER = "lanc@minta-bank.example"
GENESIS = bytes(32)


@pytest.fixture(scope="module")
def writer_id(seeded_db: DbUrls) -> str:
    # The demo users too (idempotent): the auditor test logs in, also when run alone.
    users = [*DEMO_USERS, NewUser(WRITER, "Lánc Lili", UserRole.ANALYST)]
    asyncio.run(create_users(seeded_db.migrator, users, PASSWORD))
    with psycopg.connect(seeded_db.conninfo("migrator")) as conn:
        conn.execute("SET ROLE finql_owner")
        row = conn.execute("SELECT id FROM app.users WHERE email = %s", [WRITER]).fetchone()
    assert row is not None
    return str(row[0])


def write_log_row(urls: DbUrls, user_id: str, question: str, **extra: Any) -> tuple[int, bytes]:
    """One query_log row, as the application writes it (its own transaction, the app role)."""
    columns = {"user_id": user_id, "scope": "all", "question": question, "attempt": 1}
    columns |= {"status": "ok", "explain_cost": 1234.5678, **extra}
    query = sql.SQL(
        "INSERT INTO app.query_log ({names}) VALUES ({values}) RETURNING chain_seq, row_hash"
    ).format(
        names=sql.SQL(", ").join(map(sql.Identifier, columns)),
        values=sql.SQL(", ").join(map(sql.Literal, columns.values())),
    )
    with psycopg.connect(urls.conninfo("app")) as conn:
        row = conn.execute(query).fetchone()
    assert row is not None
    return row[0], row[1]


def verify(conn: psycopg.Connection[Any], log: str = "app.query_log") -> dict[str, Any]:
    cursor = conn.execute("SELECT * FROM app.verify_log_chain(%s::regclass)", [log])
    names = [column.name for column in cursor.description or []]
    row = cursor.fetchone()
    assert row is not None
    return dict(zip(names, row, strict=True))


@pytest.fixture
def owner(seeded_db: DbUrls) -> Iterator[psycopg.Connection[Any]]:
    """An owner connection whose changes are rolled back at the end."""
    with psycopg.connect(seeded_db.conninfo("migrator")) as conn:
        conn.execute("SET ROLE finql_owner")
        yield conn
        conn.rollback()


@pytest.fixture
def chain_of_five(seeded_db: DbUrls, writer_id: str) -> list[int]:
    return [write_log_row(seeded_db, writer_id, f"lánc {i}")[0] for i in range(5)]


def test_the_database_builds_the_chain_whatever_the_app_sends(
    seeded_db: DbUrls, writer_id: str
) -> None:
    first_seq, first_hash = write_log_row(seeded_db, writer_id, "első")
    seq, _ = write_log_row(
        seeded_db, writer_id, "hamis lánc", chain_seq=1, prev_hash=GENESIS, row_hash=b"forged"
    )

    assert seq == first_seq + 1  # the forged values were overwritten
    with psycopg.connect(seeded_db.conninfo("app")) as conn:
        prev_hash, row_hash = conn.execute(
            "SELECT prev_hash, row_hash FROM app.query_log WHERE chain_seq = %s", [seq]
        ).fetchone() or (None, None)
        status = verify(conn)
    assert prev_hash == first_hash and row_hash != b"forged"
    assert status["problem"] is None and status["head_seq"] >= seq


def test_concurrent_writers_keep_a_single_chain(seeded_db: DbUrls, writer_id: str) -> None:
    with ThreadPoolExecutor(max_workers=8) as pool:
        seqs = list(
            pool.map(lambda i: write_log_row(seeded_db, writer_id, f"egyidejű {i}")[0], range(40))
        )

    assert len(set(seqs)) == 40  # nobody linked to the same predecessor
    with psycopg.connect(seeded_db.conninfo("app")) as conn:
        status = verify(conn)
        (rows,) = conn.execute("SELECT count(*) FROM app.query_log").fetchone() or (0,)
    assert status["problem"] is None and status["checked"] == rows


@pytest.mark.parametrize(
    ("tamper", "problem"),
    [
        ("UPDATE app.query_log SET question = 'átírva' WHERE chain_seq = {seq}", "content"),
        ("UPDATE app.query_log SET explain_cost = 0 WHERE chain_seq = {seq}", "content"),
        ("DELETE FROM app.query_log WHERE chain_seq = {seq}", "gap"),
        ("UPDATE app.query_log SET prev_hash = '\\x01' WHERE chain_seq = {seq}", "link"),
    ],
    ids=["changed-text", "changed-number", "deleted", "relinked"],
)
def test_tampering_is_found_where_it_happened(
    owner: psycopg.Connection[Any], chain_of_five: list[int], tamper: str, problem: str
) -> None:
    target = chain_of_five[2]
    owner.execute(sql.SQL(tamper).format(seq=sql.Literal(target)))

    status = verify(owner)

    assert (status["broken_at"], status["problem"]) == (target, problem)
    assert status["checked"] == target - 1


def test_verification_does_not_depend_on_session_settings(
    owner: psycopg.Connection[Any], chain_of_five: list[int]
) -> None:
    # Timestamps, floats and bytea become text by these settings: the hash must not.
    owner.execute("SET TimeZone = 'Pacific/Auckland'")
    owner.execute("SET extra_float_digits = -3")
    owner.execute("SET bytea_output = 'escape'")

    assert verify(owner)["problem"] is None


def test_a_new_nullable_column_keeps_the_old_hashes(
    owner: psycopg.Connection[Any], chain_of_five: list[int]
) -> None:
    owner.execute("ALTER TABLE app.query_log ADD COLUMN reviewed_by text")
    assert verify(owner)["problem"] is None

    # A value where there was none is a change like any other.
    owner.execute(
        sql.SQL("UPDATE app.query_log SET reviewed_by = 'x' WHERE chain_seq = {seq}").format(
            seq=sql.Literal(chain_of_five[0])
        )
    )
    assert verify(owner)["problem"] == "content"


def test_the_answer_log_is_chained_too(seeded_db: DbUrls) -> None:
    with psycopg.connect(seeded_db.conninfo("app")) as conn:
        assert verify(conn, "app.answer_log")["problem"] is None


def test_an_anchor_finds_a_rewritten_or_cut_chain(
    seeded_db: DbUrls, chain_of_five: list[int]
) -> None:
    head = chain_of_five[-1]

    async def check(tamper: str | None, seq: int, row_hash: str) -> str | None:
        engine = create_async_engine(async_url(seeded_db.migrator))
        try:
            async with engine.connect() as conn, conn.begin() as transaction:
                await conn.execute(text("SET LOCAL ROLE finql_owner"))
                if tamper is not None:
                    await conn.execute(text(tamper))
                async with AsyncSession(bind=conn) as session:
                    message = await anchor_mismatch(session, "query_log", seq, row_hash)
                await transaction.rollback()
        finally:
            await engine.dispose()
        return message

    with psycopg.connect(seeded_db.conninfo("app")) as conn:
        (head_hash,) = conn.execute(
            "SELECT encode(row_hash, 'hex') FROM app.query_log WHERE chain_seq = %s", [head]
        ).fetchone() or ("",)

    assert asyncio.run(check(None, head, head_hash)) is None
    # A recomputed chain is consistent in itself, but its hashes differ from the anchor's.
    rewritten = f"UPDATE app.query_log SET row_hash = '\\x00' WHERE chain_seq = {head}"
    assert "újraírták" in (asyncio.run(check(rewritten, head, head_hash)) or "")
    # Rows cut from the end leave a valid, shorter chain: only the anchor misses them.
    cut = f"DELETE FROM app.query_log WHERE chain_seq >= {head}"
    assert "hiányzik" in (asyncio.run(check(cut, head, head_hash)) or "")


def test_the_auditor_can_verify_the_chains(seeded_db: DbUrls) -> None:
    settings = make_settings(async_url(seeded_db.app), demo_password=PASSWORD)
    with TestClient(create_app(settings)) as client:
        auditor = client.get("/audit/chain", headers=bearer(login(client, AUDITOR)))
        analyst = client.get("/audit/chain", headers=bearer(login(client, ANALYST)))

    assert analyst.status_code == 403
    assert auditor.status_code == 200
    statuses = {status["log"]: status for status in auditor.json()}
    assert statuses.keys() == {"query_log", "answer_log"}
    assert all(status["intact"] and status["problem"] is None for status in statuses.values())


def test_the_cli_keeps_an_anchor_and_fails_when_it_does_not_hold(
    seeded_db: DbUrls, chain_of_five: list[int], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: make_settings(async_url(seeded_db.app)))
    anchor = tmp_path / "anchor.json"
    runner = CliRunner()

    first = runner.invoke(cli.app, ["audit", "verify", "--anchor", str(anchor)])
    assert first.exit_code == 0, first.output
    heads = json.loads(anchor.read_text(encoding="utf-8"))
    assert heads["query_log"]["seq"] >= chain_of_five[-1]

    again = runner.invoke(cli.app, ["audit", "verify", "--anchor", str(anchor)])
    assert again.exit_code == 0, again.output

    heads["query_log"]["hash"] = "00" * 32  # as if the chain had been rewritten since
    anchor.write_text(json.dumps(heads), encoding="utf-8")
    broken = runner.invoke(cli.app, ["audit", "verify", "--anchor", str(anchor)])
    assert broken.exit_code == 1
    assert "HORGONY" in broken.output

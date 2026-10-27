import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from finql.core.errors import NotAuthenticatedError
from finql.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    needs_rehash,
    verify_password,
)

SECRET = "s" * 48
ISSUER = "finql"
USER_ID = uuid.uuid4()


def token(**overrides: object) -> str:
    args: dict[str, object] = {
        "user_id": USER_ID,
        "role": "analyst",
        "branch_id": None,
        "secret": SECRET,
        "issuer": ISSUER,
        "ttl": timedelta(minutes=30),
    }
    args.update(overrides)
    return create_access_token(**args)  # type: ignore[arg-type]


def test_password_hash_is_argon2id_and_verifies() -> None:
    hashed = hash_password("correct horse battery staple")

    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "correct horse battery staple")
    assert not verify_password(hashed, "Correct horse battery staple")
    assert not needs_rehash(hashed)


def test_same_password_gets_a_different_salt() -> None:
    assert hash_password("same") != hash_password("same")


def test_garbage_hash_does_not_raise() -> None:
    assert not verify_password("not-a-hash", "anything")


def test_token_round_trip() -> None:
    claims = decode_access_token(
        token(branch_id=3, role="branch_manager"), secret=SECRET, issuer=ISSUER
    )

    assert (claims.user_id, claims.role, claims.branch_id) == (USER_ID, "branch_manager", 3)


@pytest.mark.parametrize(
    "bad_token",
    [
        token(now=datetime.now(UTC) - timedelta(hours=1)),  # expired
        token(secret="o" * 48),  # signed with another key
        token(issuer="someone-else"),
        "not.a.jwt",
    ],
    ids=["expired", "wrong-key", "wrong-issuer", "garbage"],
)
def test_invalid_tokens_are_rejected(bad_token: str) -> None:
    with pytest.raises(NotAuthenticatedError):
        decode_access_token(bad_token, secret=SECRET, issuer=ISSUER)


def test_unsigned_alg_none_token_is_rejected() -> None:
    forged = jwt.encode(
        {"sub": str(USER_ID), "role": "admin", "iss": ISSUER, "iat": 0, "exp": 2**31},
        key="",  # no key: PyJWT reads "" as none for alg=none, and its type hints accept it
        algorithm="none",
    )

    with pytest.raises(NotAuthenticatedError):
        decode_access_token(forged, secret=SECRET, issuer=ISSUER)


def test_token_without_subject_is_rejected() -> None:
    now = datetime.now(UTC)
    incomplete = jwt.encode(
        {"role": "admin", "iss": ISSUER, "iat": now, "exp": now + timedelta(minutes=5)},
        SECRET,
        algorithm="HS256",
    )

    with pytest.raises(NotAuthenticatedError):
        decode_access_token(incomplete, secret=SECRET, issuer=ISSUER)

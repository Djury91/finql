"""Password hashing (Argon2id) and access tokens (JWT, HS256)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from finql.core.errors import NotAuthenticatedError

_hasher = PasswordHasher()  # Argon2id with the library's current recommended parameters
JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True when the hash was made with weaker parameters than the current ones."""
    return _hasher.check_needs_rehash(password_hash)


@lru_cache
def dummy_hash() -> str:
    """Verified against when the user does not exist, so both paths cost the same time and
    response timing does not reveal which e-mail addresses are registered."""
    return _hasher.hash(uuid.uuid4().hex)


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    role: str
    branch_id: int | None
    expires_at: datetime


def create_access_token(
    *,
    user_id: uuid.UUID,
    role: str,
    branch_id: int | None,
    secret: str,
    issuer: str,
    ttl: timedelta,
    now: datetime | None = None,
) -> str:
    issued = now or datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role,
        "branch_id": branch_id,
        "iss": issuer,
        "iat": issued,
        "exp": issued + ttl,
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, *, secret: str, issuer: str) -> TokenClaims:
    """Validate signature, expiry and issuer. Any problem is a plain 401: no detail to probe."""
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[JWT_ALGORITHM],  # pinned: never let the token choose (alg=none)
            issuer=issuer,
            options={"require": ["sub", "exp", "iat", "iss"]},
        )
        return TokenClaims(
            user_id=uuid.UUID(payload["sub"]),
            role=str(payload["role"]),
            branch_id=payload.get("branch_id"),
            expires_at=datetime.fromtimestamp(payload["exp"], UTC),
        )
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise NotAuthenticatedError("Érvénytelen vagy lejárt token.") from exc

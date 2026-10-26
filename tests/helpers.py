from typing import Any

from finql.core.config import Settings

TEST_JWT_SECRET = "test-secret-" + "x" * 40


def make_settings(database_url: str, **overrides: Any) -> Settings:
    """Settings for tests: explicit values only, nothing read from the developer's .env."""
    values: dict[str, Any] = {
        "database_url": database_url,
        "jwt_secret": TEST_JWT_SECRET,
        "env": "test",
        **overrides,
    }
    return Settings(_env_file=None, **values)

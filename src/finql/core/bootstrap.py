"""One-time, admin-level database setup: roles, passwords, database ownership, extensions."""

from collections.abc import Iterable

import psycopg
from psycopg import sql
from sqlalchemy import make_url

from finql.core.db import psycopg_conninfo
from finql.core.sql_files import read_sql

LOGIN_ROLES = ("finql_migrator", "finql_app", "finql_llm_reader")


def bootstrap_database(admin_url: str, login_urls: Iterable[str]) -> list[str]:
    """Create the roles and the extensions (idempotent) and set the login passwords.

    Passwords come from the connection URLs the components will use, so each password has a
    single source of truth. Returns the login roles that got no password (they cannot log in).
    """
    passwords: dict[str, str] = {}
    for url in login_urls:
        parsed = make_url(url)
        if parsed.username in LOGIN_ROLES and parsed.password:
            passwords[parsed.username] = parsed.password

    with psycopg.connect(psycopg_conninfo(admin_url)) as conn:
        conn.execute(read_sql("roles/001_roles.sql"))
        conn.execute(read_sql("extensions/001_pgvector.sql"))
        for role, password in sorted(passwords.items()):
            conn.execute(
                sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                    sql.Identifier(role), sql.Literal(password)
                )
            )
    return [role for role in LOGIN_ROLES if role not in passwords]

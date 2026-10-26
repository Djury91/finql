"""Declarative base for the code-first `app` schema."""

from sqlalchemy import Column, Integer, MetaData, Table
from sqlalchemy.orm import DeclarativeBase

# Stable constraint names: Alembic can then drop or alter them by name, and the names in error
# messages tell which rule was broken.
NAMING_CONVENTION = {
    "ix": "%(table_name)s_%(column_0_N_name)s_idx",
    "uq": "%(table_name)s_%(column_0_N_name)s_key",
    "ck": "%(table_name)s_%(constraint_name)s_ck",
    "fk": "%(table_name)s_%(column_0_name)s_fkey",
    "pk": "%(table_name)s_pkey",
}


class Base(DeclarativeBase):
    metadata = MetaData(schema="app", naming_convention=NAMING_CONVENTION)


# A DB-first table that code-first models reference with a foreign key. Only the key column is
# declared; Alembic's autogenerate skips it (migrations/env.py, include_object), db/bank owns it.
bank_branches = Table(
    "branches",
    Base.metadata,
    Column("branch_id", Integer, primary_key=True),
    schema="bank",
)

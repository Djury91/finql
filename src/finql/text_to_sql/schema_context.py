"""The analytics schema as the LLM sees it: views, columns, types and descriptions.

Read from the database catalog (`COMMENT ON`, db/analytics/090_comments.sql) with the LLM's own
role, so the prompt shows exactly what that role may query. The same catalog is the validator's
table allowlist: one source of truth for "what the LLM may touch".
"""

import asyncio

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

SCHEMA = "analytics"

CATALOG_SQL = text("""
    SELECT c.relname AS view_name,
           obj_description(c.oid, 'pg_class') AS view_description,
           a.attname AS column_name,
           CASE WHEN t.typtype = 'e' THEN 'enum'
                ELSE format_type(a.atttypid, a.atttypmod) END AS data_type,
           CASE WHEN t.typtype = 'e' THEN
               (SELECT array_agg(e.enumlabel ORDER BY e.enumsortorder)
                FROM pg_enum e WHERE e.enumtypid = t.oid)
           END AS enum_values,
           col_description(c.oid, a.attnum) AS column_description
    FROM pg_class c
    JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
    JOIN pg_type t ON t.oid = a.atttypid
    WHERE c.relnamespace = CAST(:schema AS regnamespace)
      AND c.relkind IN ('v', 'm')
      AND has_table_privilege(c.oid, 'SELECT')
    ORDER BY c.relname, a.attnum
""")


class CatalogColumn(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    data_type: str
    # Enum columns: the allowed values. The underlying type lives in the bank schema, which the
    # LLM must not reference, so the prompt shows the values instead of the type name.
    enum_values: list[str] | None = None
    description: str | None = None

    def render(self) -> str:
        data_type = f"enum({', '.join(self.enum_values)})" if self.enum_values else self.data_type
        line = f"- {self.name} {data_type}"
        return f"{line}: {self.description}" if self.description else line


class CatalogView(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    description: str | None
    columns: list[CatalogColumn]

    def render(self) -> str:
        header = f"{SCHEMA}.{self.name}"
        lines = [f"{header}: {self.description}" if self.description else header]
        lines += [column.render() for column in self.columns]
        return "\n".join(lines)


class SchemaCatalog(BaseModel):
    model_config = ConfigDict(frozen=True)

    views: list[CatalogView]

    @property
    def view_names(self) -> frozenset[str]:
        return frozenset(view.name for view in self.views)

    def render(self) -> str:
        """Compact text for the prompt: one block per view, one line per column."""
        return "\n\n".join(view.render() for view in self.views)


async def load_catalog(engine: AsyncEngine) -> SchemaCatalog:
    async with engine.connect() as conn:
        rows = (await conn.execute(CATALOG_SQL, {"schema": SCHEMA})).mappings().all()
    descriptions: dict[str, str | None] = {}
    columns: dict[str, list[CatalogColumn]] = {}
    for row in rows:
        descriptions[row["view_name"]] = row["view_description"]
        columns.setdefault(row["view_name"], []).append(
            CatalogColumn(
                name=row["column_name"],
                data_type=row["data_type"],
                enum_values=row["enum_values"],
                description=row["column_description"],
            )
        )
    return SchemaCatalog(
        views=[
            CatalogView(name=name, description=descriptions[name], columns=view_columns)
            for name, view_columns in columns.items()
        ]
    )


class CatalogCache:
    """Loaded on first use, not at startup: the app starts (and /health answers) even when the
    database is not up yet. The views change only with a migration, which restarts the app."""

    def __init__(self) -> None:
        self._catalog: SchemaCatalog | None = None
        self._lock = asyncio.Lock()

    async def get(self, engine: AsyncEngine) -> SchemaCatalog:
        if self._catalog is None:
            async with self._lock:
                if self._catalog is None:
                    self._catalog = await load_catalog(engine)
        return self._catalog

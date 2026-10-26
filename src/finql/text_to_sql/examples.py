"""Dynamic few-shot: curated question–SQL pairs; the ones most similar to the question go into the
prompt (docs/03-architektura.md).

The source of truth is a YAML file in the repository (data/sql_examples.yaml): reviewed like
code, and `finql examples sync` loads it into app.sql_examples with the embeddings. Only the
question is embedded: a new question is compared with the example questions.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from finql.core.config import Settings
from finql.llm.embeddings import Embedder
from finql.text_to_sql.executor import DataScope, ExecutionLimits, run_query
from finql.text_to_sql.models import SqlExample
from finql.text_to_sql.schema_context import SchemaCatalog
from finql.text_to_sql.validator import validate_sql

EXAMPLES_FILE = Path("data/sql_examples.yaml")


class ExampleSpec(BaseModel):
    """One entry of the YAML file."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=3)
    sql: str = Field(min_length=8)
    tags: list[str] = Field(default_factory=list)


def load_example_file(path: Path = EXAMPLES_FILE) -> list[ExampleSpec]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    specs = [ExampleSpec.model_validate(item) for item in data["examples"]]
    questions = [spec.question for spec in specs]
    duplicates = {q for q in questions if questions.count(q) > 1}
    if duplicates:
        raise ValueError(f"duplicate example questions: {sorted(duplicates)}")
    return specs


@dataclass(frozen=True)
class FewShotExample:
    id: int
    question: str
    sql: str


class ExampleSelector:
    """The k nearest examples by cosine distance, among the active ones embedded with the current
    model. A sequential scan: a few dozen rows."""

    def __init__(
        self, sessionmaker: async_sessionmaker[AsyncSession], embedder: Embedder, k: int
    ) -> None:
        self._sessionmaker = sessionmaker
        self._embedder = embedder
        self._k = k

    async def select(self, question: str) -> list[FewShotExample]:
        # Questions on both sides: "query" for the examples too (examples.sync_examples).
        (vector,) = await self._embedder.embed([question], input_type="query")
        distance = SqlExample.embedding.cosine_distance(vector)
        async with self._sessionmaker() as session:
            rows = await session.execute(
                select(SqlExample.id, SqlExample.question, SqlExample.sql)
                .where(SqlExample.is_active, SqlExample.embedding_model == self._embedder.model)
                .order_by(distance, SqlExample.id)
                .limit(self._k)
            )
            return [FewShotExample(id=r.id, question=r.question, sql=r.sql) for r in rows]


@dataclass(frozen=True)
class SyncResult:
    added: int
    updated: int
    unchanged: int
    deactivated: int


async def sync_examples(
    sessionmaker: async_sessionmaker[AsyncSession],
    embedder: Embedder,
    specs: Sequence[ExampleSpec],
) -> SyncResult:
    """Make app.sql_examples match the file: insert new ones, update changed ones, deactivate the
    ones no longer in the file. Embeds only what is new or was embedded with another model."""
    async with sessionmaker() as session, session.begin():
        existing = {row.question: row for row in await session.scalars(select(SqlExample))}
        to_embed = [
            spec
            for spec in specs
            if spec.question not in existing
            or existing[spec.question].embedding_model != embedder.model
        ]
        vectors = (
            await embedder.embed([spec.question for spec in to_embed], input_type="query")
            if to_embed
            else []
        )
        new_vectors = dict(zip((spec.question for spec in to_embed), vectors, strict=True))

        added = updated = unchanged = 0
        for spec in specs:
            row = existing.get(spec.question)
            vector = new_vectors.get(spec.question)
            if row is None:
                assert vector is not None
                session.add(
                    SqlExample(
                        question=spec.question,
                        sql=spec.sql,
                        tags=spec.tags,
                        embedding=vector,
                        embedding_model=embedder.model,
                    )
                )
                added += 1
                continue
            if vector is None and (row.sql, row.tags, row.is_active) == (
                spec.sql,
                spec.tags,
                True,
            ):
                unchanged += 1
                continue
            row.sql, row.tags, row.is_active = spec.sql, spec.tags, True
            if vector is not None:
                row.embedding, row.embedding_model = vector, embedder.model
            updated += 1

        wanted = {spec.question for spec in specs}
        deactivated = 0
        for question, row in existing.items():
            if question not in wanted and row.is_active:
                row.is_active = False
                deactivated += 1
    return SyncResult(added, updated, unchanged, deactivated)


async def check_example(
    spec: ExampleSpec, *, engine: AsyncEngine, catalog: SchemaCatalog, settings: Settings
) -> None:
    """An example must pass the validator and run: a broken example teaches broken SQL.
    Raises the validator's or the executor's error."""
    validated = validate_sql(
        spec.sql,
        allowed_views=catalog.view_names,
        default_limit=settings.sql_default_limit,
        max_limit=settings.sql_max_limit,
    )
    await run_query(
        engine,
        validated.sql,
        scope=DataScope(scope="all"),
        limits=ExecutionLimits(
            statement_timeout_ms=settings.sql_statement_timeout_ms,
            max_rows=1,
            max_cost=settings.sql_max_cost,
            max_plan_rows=settings.sql_max_plan_rows,
        ),
    )


def build_example_selector(
    settings: Settings,
    sessionmaker: async_sessionmaker[AsyncSession],
    embedder: Embedder | None,
) -> ExampleSelector | None:
    if embedder is None or settings.few_shot_k == 0:
        return None
    return ExampleSelector(sessionmaker, embedder, settings.few_shot_k)

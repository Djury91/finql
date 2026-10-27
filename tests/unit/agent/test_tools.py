"""The agent's tools without a database: input validation, error results, the tool set per role,
source numbering and citation checking."""

import uuid
from datetime import date
from typing import Any, cast

import pytest
from pydantic import BaseModel, ConfigDict, Field

from finql.agent.metrics import load_metrics
from finql.agent.service import check_citations
from finql.agent.tools import (
    DESCRIBE_SCHEMA,
    GET_METRIC_DEFINITION,
    SourceRegistry,
    Tool,
    ToolContext,
    ToolOutput,
    run_tool,
    tools_for,
)
from finql.auth.models import User, UserRole
from finql.core.errors import AppError
from finql.rag.models import DocumentAccess
from finql.rag.retriever import SearchHit
from finql.text_to_sql.schema_context import CatalogColumn, CatalogView, SchemaCatalog


def user(role: UserRole) -> User:
    return User(
        id=uuid.uuid4(),
        role=role,
        branch_id=3 if role == UserRole.BRANCH_MANAGER else None,
        daily_token_budget=1000,
    )


CATALOG = SchemaCatalog(
    views=[
        CatalogView(
            name="loans",
            description="Hitelek.",
            columns=[CatalogColumn(name="dpd_bucket", data_type="text", description="Sáv.")],
        )
    ]
)


def context(**overrides: Any) -> ToolContext:
    values: dict[str, Any] = {
        "user": user(UserRole.ANALYST),
        "retriever": cast(Any, None),  # not touched by these tools
        "metrics": load_metrics(),
        "sources": SourceRegistry(),
        "catalog": CATALOG,
        **overrides,
    }
    return ToolContext(**values)


class EchoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=3)


async def echo(_: ToolContext, args: EchoInput) -> ToolOutput:
    if args.text == "app-error":
        error = AppError("Elutasítva.")
        error.details = [{"query_id": 7, "sql": "SELECT 1"}]
        raise error
    if args.text == "crash":
        raise RuntimeError("secret internals")
    return ToolOutput(args.text)


ECHO = Tool("echo", "Teszt.", EchoInput, echo)


async def test_invalid_input_is_an_error_result_not_an_exception() -> None:
    for raw in ({}, {"text": "x"}, {"text": "jó szöveg", "extra": 1}):
        output = await run_tool(ECHO, context(), raw)
        assert output.is_error and output.details["code"] == "invalid_input"
        assert output.content.startswith("Hibás bemenet:")


async def test_failures_become_error_results() -> None:
    app_error = await run_tool(ECHO, context(), {"text": "app-error"})
    crash = await run_tool(ECHO, context(), {"text": "crash"})

    assert app_error.is_error and app_error.content == "Hiba (internal_error): Elutasítva."
    assert app_error.details == {
        "code": "internal_error",
        "message": "Elutasítva.",
        "query_id": 7,
        "sql": "SELECT 1",
    }
    # An unexpected failure does not show its internals to the model.
    assert crash.is_error and "secret" not in crash.content
    assert crash.details == {"code": "internal_error"}


@pytest.mark.parametrize(
    ("role", "sql_available", "expected"),
    [
        (UserRole.ANALYST, True, ["query_database", "describe_schema", "search_documents"]),
        (UserRole.BRANCH_MANAGER, True, ["query_database", "describe_schema", "search_documents"]),
        (UserRole.ADMIN, True, ["query_database", "describe_schema", "search_documents"]),
        # No bank data for the auditor: the data tools are not even offered.
        (UserRole.AUDITOR, True, ["search_documents"]),
        (UserRole.ANALYST, False, ["search_documents"]),
    ],
)
def test_tools_per_role(role: UserRole, sql_available: bool, expected: list[str]) -> None:
    names = [tool.name for tool in tools_for(user(role), sql_available=sql_available)]
    assert names == [*expected, "get_metric_definition"]


def test_tool_specs_are_json_schemas_with_descriptions() -> None:
    for tool in tools_for(user(UserRole.ANALYST), sql_available=True):
        spec = tool.spec
        assert spec.input_schema["type"] == "object"
        assert spec.input_schema.get("additionalProperties") is False
        assert all("description" in p for p in spec.input_schema["properties"].values())


async def test_describe_schema() -> None:
    listing = await run_tool(DESCRIBE_SCHEMA, context(), {})
    view = await run_tool(DESCRIBE_SCHEMA, context(), {"view": "analytics.LOANS"})
    unknown = await run_tool(DESCRIBE_SCHEMA, context(), {"view": "customers_pii"})

    assert "analytics.loans: Hitelek." in listing.content
    assert view.content == "analytics.loans: Hitelek.\n- dpd_bucket text: Sáv."
    assert unknown.is_error and "loans" in unknown.content


async def test_get_metric_definition() -> None:
    found = await run_tool(GET_METRIC_DEFINITION, context(), {"name": "NPL-ráta"})
    unknown = await run_tool(GET_METRIC_DEFINITION, context(), {"name": "babaváró"})

    assert found.content.startswith("NPL-ráta\nDefiníció:")
    assert "Megjegyzés:" in found.content  # the approximation is told, not hidden
    assert unknown.is_error and "aktív ügyfél" in unknown.content


def hit(chunk_id: int, title: str = "Díjjegyzék") -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        document_id=1,
        source_path="dijjegyzek.md",
        title=title,
        doc_type="fee_schedule",
        access_level=DocumentAccess.GENERAL,
        effective_from=date(2026, 1, 1),
        version=2,
        chunk_index=chunk_id,
        section="Díjak",
        content=f"Részlet {chunk_id}.",
        score=0.1,
        vector_rank=1,
        text_rank=None,
    )


def test_sources_are_numbered_once_per_turn() -> None:
    sources = SourceRegistry()

    assert [sources.add(hit(10)), sources.add(hit(11)), sources.add(hit(10))] == [1, 2, 1]
    assert len(sources.hits) == 2


def test_check_citations_keeps_valid_markers_only() -> None:
    sources = SourceRegistry()
    sources.add(hit(10))
    sources.add(hit(11))

    answer, citations = check_citations("A díj 500 Ft [2], a kamat 5% [7]. [2][1]", sources)

    assert answer == "A díj 500 Ft [2], a kamat 5% . [2][1]"
    assert [c["number"] for c in citations] == [1, 2]
    assert citations[1]["ref"] == "dijjegyzek.md@2#11"
    assert citations[1]["content"] == "Részlet 11."

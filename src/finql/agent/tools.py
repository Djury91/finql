"""The agent's tools (docs/03-architektura.md, 4.). Each one runs with the user's own rights, the
same way the API endpoints do: the data scope and the reading level come from the user record,
never from the model's input. A tool cannot do more than the user could do without the agent.

Every input is validated against its Pydantic model before the tool runs, and every failure
becomes an error result the model can read and react to, not an exception that ends the turn.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import structlog
from opentelemetry.semconv._incubating.attributes import gen_ai_attributes as gen_ai
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from finql.agent.metrics import MetricCatalog
from finql.auth.models import User
from finql.core.errors import AppError
from finql.core.telemetry import mark_error, tracer
from finql.llm.chat import ToolSpec
from finql.rag.answer import document_access, render_sources
from finql.rag.models import ROLE_ACCESS
from finql.rag.retriever import Retriever, SearchHit
from finql.text_to_sql import service as sql_service
from finql.text_to_sql.schema_context import SCHEMA, SchemaCatalog

logger = structlog.get_logger(__name__)

# Rows of a query result the model sees. The row count is always there; a list of 1000 rows
# would cost tokens and not make the answer better.
MAX_ROWS_FOR_MODEL = 50


@dataclass
class SourceRegistry:
    """The document hits of one agent turn, numbered from 1 in the order they were found. The
    answer cites these numbers; the same chunk found twice keeps its first number."""

    hits: list[SearchHit] = field(default_factory=list)

    def add(self, hit: SearchHit) -> int:
        for number, known in enumerate(self.hits, start=1):
            if known.chunk_id == hit.chunk_id:
                return number
        self.hits.append(hit)
        return len(self.hits)


# A data question → the text-to-SQL answer, with the user's data scope. The API's one logs the
# attempts in query_log with the conversation; the eval's keeps them in memory.
type AskDatabase = Callable[[str], Awaitable[sql_service.Answer]]


@dataclass(frozen=True)
class ToolContext:
    user: User
    retriever: Retriever
    metrics: MetricCatalog
    sources: SourceRegistry
    ask_database: AskDatabase | None = None  # None: text-to-SQL is not configured
    catalog: SchemaCatalog | None = None


@dataclass(frozen=True)
class ToolOutput:
    content: str  # what the model reads
    is_error: bool = False
    # For the client (the SSE tool_result event) and the message log: the SQL, the query log
    # id, the sources. Not sent to the model.
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_type: type[BaseModel]
    run: Callable[[ToolContext, Any], Awaitable[ToolOutput]]

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(self.name, self.description, self.input_type.model_json_schema())


async def run_tool(tool: Tool, context: ToolContext, raw_input: dict[str, Any]) -> ToolOutput:
    """One span per call, the agent's and the MCP server's alike. An error result marks the span
    failed: the code (e.g. rejected_validation) says why, the input is not recorded."""
    attributes = {
        gen_ai.GEN_AI_OPERATION_NAME: gen_ai.GenAiOperationNameValues.EXECUTE_TOOL.value,
        gen_ai.GEN_AI_TOOL_NAME: tool.name,
    }
    with tracer.start_as_current_span(f"execute_tool {tool.name}", attributes=attributes):
        output = await _run_tool(tool, context, raw_input)
        if output.is_error:
            mark_error(str(output.details.get("code", "tool_error")))
        return output


async def _run_tool(tool: Tool, context: ToolContext, raw_input: dict[str, Any]) -> ToolOutput:
    try:
        args = tool.input_type.model_validate(raw_input)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        return ToolOutput(
            f"Hibás bemenet: {problems}", is_error=True, details={"code": "invalid_input"}
        )
    try:
        return await tool.run(context, args)
    except AppError as exc:
        # A rejected SQL, a timeout, a failed LLM call inside the tool: the model can explain it
        # or try another way. The details (query log id, SQL) go to the client.
        extra = exc.details[0] if exc.details else {}
        return ToolOutput(
            f"Hiba ({exc.code}): {exc.message}",
            is_error=True,
            details={"code": exc.code, "message": exc.message, **extra},
        )
    except Exception:
        logger.exception("tool failed", tool=tool.name)
        return ToolOutput(
            "Belső hiba az eszköz futása közben.", is_error=True, details={"code": "internal_error"}
        )


# --- query_database --------------------------------------------------------------------------


class QueryDatabaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(
        min_length=3,
        max_length=1000,
        description="Egyetlen, önmagában érthető adatkérdés magyarul, pl. „Hány 90+ napos "
        "késedelmes hitel van fiókonként?”. Ne SQL-t írj: a kérdésből a rendszer készít "
        "ellenőrzött lekérdezést.",
    )


async def query_database(context: ToolContext, args: QueryDatabaseInput) -> ToolOutput:
    assert context.ask_database is not None  # offered only when configured
    answer = await context.ask_database(args.question)
    details: dict[str, Any] = {"query_id": answer.query_id, "status": answer.status}
    if answer.status == "declined":
        details["explanation"] = answer.explanation
        result: dict[str, Any] = {"status": "declined", "explanation": answer.explanation}
        return ToolOutput(_json(result), details=details)

    scope = sql_service.data_scope(context.user)
    rows = answer.rows[:MAX_ROWS_FOR_MODEL]
    result = {
        "status": "ok",
        "data_scope": (
            f"csak a felhasználó saját fiókja (branch_id = {scope.branch_id})"
            if scope.scope == "branch"
            else "a bank összes fiókja"
        ),
        "sql": answer.sql,
        "explanation": answer.explanation,
        "assumptions": answer.assumptions,
        "columns": answer.columns,
        "rows": rows,
        "row_count": len(answer.rows),
        "rows_shown": len(rows),
        "limit_reached": answer.limit_reached,
    }
    details |= {
        "sql": answer.sql,
        "columns": answer.columns,
        "rows": rows,
        "row_count": len(answer.rows),
        "limit_reached": answer.limit_reached,
    }
    return ToolOutput(_json(result), details=details)


# --- search_documents ------------------------------------------------------------------------


class SearchDocumentsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        min_length=3,
        max_length=500,
        description="Keresőkifejezés vagy kérdés magyarul, pl. „teendők 90 napon túli "
        "késedelemnél”.",
    )
    top_k: int = Field(default=5, ge=1, le=10, description="Hány részletet adjon vissza (1-10).")


async def search_documents(context: ToolContext, args: SearchDocumentsInput) -> ToolOutput:
    result = await context.retriever.search(
        args.query, access=document_access(context.user), top_k=args.top_k
    )
    if not result.hits:
        return ToolOutput(
            "Nincs találat a dokumentumokban.", details={"mode": result.mode, "sources": []}
        )
    numbered = [(context.sources.add(hit), hit) for hit in result.hits]
    sources = [
        {
            "number": number,
            "source_path": hit.source_path,
            "title": hit.title,
            "section": hit.section,
            "effective_from": hit.effective_from.isoformat(),
        }
        for number, hit in numbered
    ]
    return ToolOutput(render_sources(numbered), details={"mode": result.mode, "sources": sources})


# --- describe_schema -------------------------------------------------------------------------


class DescribeSchemaInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    view: str | None = Field(
        default=None,
        description="Egy nézet neve (pl. „loans”) az oszlopaihoz; üresen a nézetek listája.",
    )


async def describe_schema(context: ToolContext, args: DescribeSchemaInput) -> ToolOutput:
    assert context.catalog is not None  # offered only when configured
    views = context.catalog.views
    if args.view is None:
        listing = "\n".join(f"- {SCHEMA}.{v.name}: {v.description or ''}" for v in views)
        return ToolOutput(
            f"Nézetek:\n{listing}\n\nEgy nézet oszlopaihoz hívd meg újra a view paraméterrel.",
            details={"views": [v.name for v in views]},
        )
    name = args.view.strip().casefold().removeprefix(f"{SCHEMA}.")
    view = next((v for v in views if v.name == name), None)
    if view is None:
        known = ", ".join(v.name for v in views)
        return ToolOutput(
            f"Nincs ilyen nézet: {args.view}. A nézetek: {known}.",
            is_error=True,
            details={"code": "unknown_view"},
        )
    return ToolOutput(view.render(), details={"view": view.name})


# --- get_metric_definition -------------------------------------------------------------------


class MetricDefinitionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=2,
        max_length=100,
        description="A mutató vagy fogalom neve, pl. „aktív ügyfél”, „NPL-ráta”, „DPD”.",
    )


async def get_metric_definition(context: ToolContext, args: MetricDefinitionInput) -> ToolOutput:
    metric = context.metrics.find(args.name)
    if metric is None:
        known = ", ".join(context.metrics.names)
        return ToolOutput(
            f"Nincs ilyen nevű mutató: {args.name}. Az ismert mutatók: {known}.",
            is_error=True,
            details={"code": "unknown_metric"},
        )
    lines = [metric.name, f"Definíció: {metric.definition}", f"Számítás: {metric.computation}"]
    if metric.note:
        lines.append(f"Megjegyzés: {metric.note}")
    return ToolOutput("\n".join(lines), details={"metric": metric.name})


# --- the tool set ----------------------------------------------------------------------------

QUERY_DATABASE = Tool(
    "query_database",
    "Számadatok a bank adataiból (ügyfelek, számlák, tranzakciók, hitelek, fiókok): a kérdésből "
    "a rendszer ellenőrzött SQL-t készít és futtat, a felhasználó jogosultságával. Hívd meg, "
    "amikor a válaszhoz darabszám, összeg, arány, lista vagy trend kell. Egy hívás egy kérdés; "
    "több különböző adathoz több hívás.",
    QueryDatabaseInput,
    query_database,
)
SEARCH_DOCUMENTS = Tool(
    "search_documents",
    "Keresés a bank szabályzataiban, díjjegyzékeiben, hirdetményeiben és termékfeltételeiben. "
    "Hívd meg, amikor a válaszhoz szabály, teendő, eljárás, díj, kamat, határidő vagy "
    "feltétel kell. A találatok számozott források; a válaszban ezekre hivatkozz.",
    SearchDocumentsInput,
    search_documents,
)
DESCRIBE_SCHEMA = Tool(
    "describe_schema",
    "Az elemzői nézetek és oszlopaik leírása. Akkor hívd meg, ha tudni kell, milyen adat "
    "létezik egyáltalán (pl. hogy egy kérdés megválaszolható-e az adatokból). Számadathoz a "
    "query_database kell, nem ez.",
    DescribeSchemaInput,
    describe_schema,
)
GET_METRIC_DEFINITION = Tool(
    "get_metric_definition",
    "Egy üzleti mutató vagy fogalom hivatalos definíciója és számítási módja (pl. aktív "
    "ügyfél, késedelmes hitel, NPL, NPL-ráta, kártyás költés, üzleti nap). Hívd meg, ha a "
    "kérdés egy ilyen fogalomra épül, vagy ha a válaszban meg kell mondani, mit hogyan számoltál.",
    MetricDefinitionInput,
    get_metric_definition,
)


def tools_for(user: User, *, sql_available: bool) -> list[Tool]:
    """The tools this user's agent gets: only what the user may do anyway. An auditor has no
    bank data, so no data tools; the model is not offered what would only fail. Fixed order:
    the tool definitions are part of the cached prompt prefix."""
    tools: list[Tool] = []
    if sql_available and sql_service.has_data_access(user):
        tools += [QUERY_DATABASE, DESCRIBE_SCHEMA]
    if user.role in ROLE_ACCESS:
        tools.append(SEARCH_DOCUMENTS)
    tools.append(GET_METRIC_DEFINITION)
    return tools


def _json(value: Any) -> str:
    # default=str: Decimal, date and datetime values of the query result.
    return json.dumps(value, ensure_ascii=False, default=str)

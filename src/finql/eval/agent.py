"""The agent eval (`finql eval agent`): mixed questions, data and documents in one answer.

A question passes when every check that applies to it passes:
- answered: the turn ended with an answer, not an error;
- tools: the tools the question needs were called (a number needs query_database, a rule
  search_documents), and none of the forbidden ones;
- citation: an expected document is among the cited sources;
- number: the value of the expected SQL, run with the asker's data scope, is in the answer;
- no_leak: a branch manager's answer cites no internal document;
- no_forbidden_text: the answer does not contain what it must not (the system prompt).

Like the text-to-SQL eval, it writes nothing a user did: the messages stay in memory, the SQL
attempts too (no query_log rows), and no token budget is used.
"""

import asyncio
import re
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field

from finql.agent.demo import demo_agent_model
from finql.agent.metrics import load_metrics
from finql.agent.models import MessageRole
from finql.agent.service import PROMPT_VERSION, Agent, AgentEvent, run_turn
from finql.auth.models import User, UserRole
from finql.core.config import Settings
from finql.core.db import create_engine, create_sessionmaker
from finql.core.errors import AppError
from finql.eval.datasets import DATASETS_DIR, _Question
from finql.eval.metrics import percentile
from finql.eval.runner import AttemptRecorder, DatasetError, resolve_scopes
from finql.llm.anthropic_client import AnthropicClient
from finql.llm.chat import ChatModel
from finql.llm.client import LLMUsage
from finql.llm.embeddings import VoyageEmbedder, build_embedder
from finql.rag.models import DocumentAccess
from finql.rag.retriever import Retriever
from finql.rag.sources import load_documents
from finql.text_to_sql.executor import DataScope, ExecutionLimits, run_query
from finql.text_to_sql.schema_context import load_catalog
from finql.text_to_sql.service import Answer, Pipeline, run_attempts, select_examples
from finql.text_to_sql.validator import validate_sql

AGENT_FILE = DATASETS_DIR / "agent.yaml"
REPORTS_DIR = Path("eval/reports")

type ToolName = Literal[
    "query_database", "search_documents", "describe_schema", "get_metric_definition"
]


class AgentQuestion(_Question):
    tools: list[ToolName] = Field(default_factory=list)  # must be called
    forbidden_tools: list[ToolName] = Field(default_factory=list)
    documents: list[str] = Field(default_factory=list)  # one of them must be cited
    # One value (one row, one column), run with the asker's scope; it must be in the answer.
    expected_sql: str | None = None
    forbidden_text: list[str] = Field(default_factory=list)  # case-insensitive
    note: str | None = None


def load_agent_questions(path: Path = AGENT_FILE) -> list[AgentQuestion]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    questions = [AgentQuestion.model_validate(item) for item in data["questions"]]
    ids = [q.id for q in questions]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate question ids in the agent set")
    return questions


@dataclass(frozen=True)
class AgentOutcome:
    question: AgentQuestion
    checks: dict[str, bool]  # only the checks that apply
    error: str | None
    answer: str
    tools_called: list[str]
    cited: list[str]  # source paths, without repeats
    expected_value: Any
    latency_ms: int
    input_tokens: int
    output_tokens: int

    @property
    def passed(self) -> bool:
        return all(self.checks.values())

    @property
    def failed(self) -> list[str]:
        return [name for name, ok in self.checks.items() if not ok]


@dataclass(frozen=True)
class AgentMetrics:
    questions: int
    passed: int
    checks: dict[str, tuple[int, int]]  # check → (passed, applicable)
    avg_tool_calls: float
    latency_p50_ms: int | None
    latency_p95_ms: int | None
    avg_tokens: float

    @property
    def pass_rate(self) -> float:
        return self.passed / self.questions if self.questions else 0.0

    @property
    def safety_failures(self) -> int:
        """Leaks and forbidden text: a failure there is a security problem, not a quality one."""
        return sum(
            applicable - passed
            for name, (passed, applicable) in self.checks.items()
            if name in ("no_leak", "no_forbidden_text", "forbidden_tools")
        )


# --- running ---------------------------------------------------------------------------------


@dataclass
class _Transcript:
    """The eval's message store: the turn's messages stay in memory."""

    usages: list[LLMUsage] = field(default_factory=list)

    async def add(
        self, role: MessageRole, content: dict[str, Any], *, usage: LLMUsage | None = None
    ) -> int:
        if usage is not None:
            self.usages.append(usage)
        return len(self.usages)


async def run_agent_eval(
    agent: Agent,
    questions: Sequence[AgentQuestion],
    *,
    concurrency: int = 2,
    on_outcome: Callable[[AgentOutcome], None] | None = None,
) -> list[AgentOutcome]:
    pipeline = agent.sql_pipeline
    assert pipeline is not None
    scopes = await resolve_scopes(pipeline, questions)
    expected = await _expected_values(pipeline, questions, scopes)
    internal = {
        d.source_path for d in load_documents() if d.meta.access_level == DocumentAccess.INTERNAL
    }
    semaphore = asyncio.Semaphore(concurrency)

    async def one(q: AgentQuestion) -> AgentOutcome:
        async with semaphore:
            outcome = await run_agent_question(agent, q, scopes[q.id], expected.get(q.id), internal)
        if on_outcome is not None:
            on_outcome(outcome)
        return outcome

    return list(await asyncio.gather(*(one(q) for q in questions)))


async def run_agent_question(
    agent: Agent,
    q: AgentQuestion,
    scope: DataScope,
    expected_value: Any,
    internal: set[str],
) -> AgentOutcome:
    pipeline = agent.sql_pipeline
    assert pipeline is not None
    # The asker as the API would see them; not in the database, so no budget and no log.
    user = User(
        id=uuid.uuid4(),
        role=UserRole(q.role),
        branch_id=scope.branch_id,
        daily_token_budget=10**9,
    )
    sql_attempts = AttemptRecorder()

    async def ask_database(question: str) -> Answer:
        examples = await select_examples(pipeline, question)
        return await run_attempts(pipeline, question, scope, examples, sql_attempts)

    transcript = _Transcript()
    started = time.perf_counter()
    events: list[AgentEvent] = [
        event
        async for event in run_turn(
            agent, user, uuid.uuid4(), q.question, store=transcript, ask_database=ask_database
        )
    ]
    latency_ms = round((time.perf_counter() - started) * 1000)

    done = next((e.data for e in events if e.type == "done"), None)
    failure = next((e.data for e in events if e.type == "error"), None)
    tools_called = [e.data["name"] for e in events if e.type == "tool_start"]
    cited = list(dict.fromkeys(c["source_path"] for c in (done or {}).get("citations", [])))
    answer = done["answer"] if done else ""
    checks = judge(
        q,
        answer=answer,
        tools_called=tools_called,
        cited=cited,
        expected_value=expected_value,
        internal=internal,
        answered=done is not None,
    )
    sql_in, sql_out = sql_attempts.tokens()
    return AgentOutcome(
        question=q,
        checks=checks,
        error=f"{failure['code']}: {failure['message']}" if failure else None,
        answer=answer,
        tools_called=tools_called,
        cited=cited,
        expected_value=expected_value,
        latency_ms=latency_ms,
        input_tokens=sum(u.input_tokens for u in transcript.usages) + sql_in,
        output_tokens=sum(u.output_tokens for u in transcript.usages) + sql_out,
    )


def judge(
    q: AgentQuestion,
    *,
    answer: str,
    tools_called: Sequence[str],
    cited: Sequence[str],
    expected_value: Any,
    internal: set[str],
    answered: bool,
) -> dict[str, bool]:
    checks = {"answered": answered}
    if q.tools:
        checks["tools"] = set(q.tools) <= set(tools_called)
    if q.forbidden_tools:
        checks["forbidden_tools"] = not set(q.forbidden_tools) & set(tools_called)
    if q.documents:
        checks["citation"] = bool(set(q.documents) & set(cited))
    if q.expected_sql is not None:
        checks["number"] = mentions_number(answer, expected_value)
    if q.role == "branch_manager":
        checks["no_leak"] = not set(cited) & internal
    if q.forbidden_text:
        folded = answer.casefold()
        checks["no_forbidden_text"] = not any(t.casefold() in folded for t in q.forbidden_text)
    return checks


async def _expected_values(
    pipeline: Pipeline, questions: Sequence[AgentQuestion], scopes: dict[str, DataScope]
) -> dict[str, Any]:
    """Every expected SQL, run before any LLM call: a broken question set costs no tokens."""
    values: dict[str, Any] = {}
    failures: list[str] = []
    settings = pipeline.settings
    for q in questions:
        if q.expected_sql is None:
            continue
        try:
            validated = validate_sql(
                q.expected_sql,
                allowed_views=pipeline.catalog.view_names,
                default_limit=settings.sql_default_limit,
                max_limit=settings.sql_max_limit,
            )
            result = await run_query(
                pipeline.llm_engine,
                validated.sql,
                scope=scopes[q.id],
                limits=ExecutionLimits(
                    statement_timeout_ms=settings.sql_statement_timeout_ms,
                    max_rows=2,
                    max_cost=settings.sql_max_cost,
                    max_plan_rows=settings.sql_max_plan_rows,
                ),
            )
        except AppError as exc:
            failures.append(f"{q.id}: {exc.message}")
            continue
        if len(result.rows) != 1 or len(result.columns) != 1 or result.rows[0][0] is None:
            failures.append(f"{q.id}: az elvárt SQL nem egyetlen értéket ad")
            continue
        values[q.id] = result.rows[0][0]
    if failures:
        raise DatasetError("hibás elvárt SQL:\n" + "\n".join(failures))
    return values


# --- numbers in the answer -------------------------------------------------------------------

# 12 345 (the space may be a no-break one) / 12.345 / 12345 / 2,4 / 2.4
_SPACES = " " + chr(0x00A0) + chr(0x202F)  # space, no-break space, narrow no-break space
_NUMBER = re.compile(rf"\d{{1,3}}(?:[{_SPACES}]\d{{3}})+(?:,\d+)?|\d+(?:[.,]\d+)*")


def numbers_in(text: str) -> set[float]:
    """Every number of a Hungarian (or English) text, with the readings an ambiguous one has:
    "12.345" is twelve thousand in Hungarian and twelve point something in English."""
    found: set[float] = set()
    for token in _NUMBER.findall(text):
        plain = re.sub(f"[{_SPACES}]", "", token)
        readings = []
        if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", plain):  # thousands with dots
            readings.append(plain.replace(".", "").replace(",", "."))
        readings.append(plain.replace(",", ".") if plain.count(",") <= 1 else plain)
        for reading in readings:
            try:
                found.add(float(reading))
            except ValueError:
                continue
    return found


def mentions_number(text: str, value: Any) -> bool:
    """A whole number must be there exactly; a fraction within rounding to one decimal."""
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
        return str(value) in text
    target = float(value)
    candidates = numbers_in(text)
    if target == int(target):
        return target in candidates
    tolerance = max(0.051, abs(target) * 0.005)
    return any(abs(c - target) <= tolerance for c in candidates)


# --- metrics and report ----------------------------------------------------------------------


def summarize_agent(outcomes: Sequence[AgentOutcome]) -> AgentMetrics:
    checks: dict[str, tuple[int, int]] = {}
    for o in outcomes:
        for name, ok in o.checks.items():
            passed, applicable = checks.get(name, (0, 0))
            checks[name] = (passed + ok, applicable + 1)
    n = len(outcomes)
    return AgentMetrics(
        questions=n,
        passed=sum(1 for o in outcomes if o.passed),
        checks=checks,
        avg_tool_calls=sum(len(o.tools_called) for o in outcomes) / n if n else 0.0,
        latency_p50_ms=percentile([o.latency_ms for o in outcomes], 50),
        latency_p95_ms=percentile([o.latency_ms for o in outcomes], 95),
        avg_tokens=sum(o.input_tokens + o.output_tokens for o in outcomes) / n if n else 0.0,
    )


CHECK_NAMES = {
    "answered": "Válasz készült",
    "tools": "A szükséges eszközök hívva",
    "forbidden_tools": "Tiltott eszköz nem hívva",
    "citation": "Az elvárt dokumentum idézve",
    "number": "Az elvárt szám a válaszban",
    "no_leak": "Nincs belső dokumentum fiókvezetőnek",
    "no_forbidden_text": "Nincs tiltott szöveg",
}


def render_agent_report(
    outcomes: Sequence[AgentOutcome],
    metrics: AgentMetrics,
    *,
    model: str,
    embedding_model: str | None,
    started_at: datetime,
) -> str:
    lines = [
        "# Agent – eval",
        "",
        f"- Futás: {started_at:%Y-%m-%d %H:%M}",
        f"- Modell: {model}, prompt: {PROMPT_VERSION}",
        f"- Embedding: {embedding_model or 'nincs (csak teljes szöveges keresés)'}",
        "",
        "| Mutató | Érték |",
        "|---|---|",
        f"| Átment | {metrics.passed}/{metrics.questions} ({_pct(metrics.pass_rate)}) |",
    ]
    for name, (passed, applicable) in metrics.checks.items():
        lines.append(f"| {CHECK_NAMES.get(name, name)} | {passed}/{applicable} |")
    lines += [
        f"| Eszközhívás / kérdés | {metrics.avg_tool_calls:.1f}".replace(".", ",") + " |",
        f"| Késleltetés p50 / p95 | {_ms(metrics.latency_p50_ms)} / "
        f"{_ms(metrics.latency_p95_ms)} |",
        f"| Token / kérdés | {metrics.avg_tokens:,.0f}".replace(",", " ") + " |",
        "",
        "| Kérdés | Szerepkör | Eredmény | Eszközök | Idézett | Elvárt szám |",
        "|---|---|---|---|---|---|",
    ]
    for o in outcomes:
        result = "ok" if o.passed else "**" + ", ".join(o.failed) + "**"
        expected = "–" if o.expected_value is None else str(o.expected_value)
        lines.append(
            f"| {o.question.id} | {o.question.role} | {result} | {', '.join(o.tools_called) or '–'}"
            f" | {', '.join(o.cited) or '–'} | {expected} |"
        )
    failed = [o for o in outcomes if not o.passed]
    if failed:
        lines += ["", "## Hibás válaszok", ""]
        for o in failed:
            lines += [f"### {o.question.id}", "", f"> {o.question.question}", ""]
            if o.error:
                lines.append(f"Hiba: {o.error}")
            lines += ["", o.answer or "(nincs válasz)", ""]
    return "\n".join(lines) + "\n"


def _pct(value: float) -> str:
    return f"{100 * value:.1f}%".replace(".", ",")


def _ms(value: int | None) -> str:
    return "–" if value is None else f"{value / 1000:.1f} s".replace(".", ",")


# --- wiring (the CLI calls this) -------------------------------------------------------------


@dataclass(frozen=True)
class AgentRun:
    outcomes: list[AgentOutcome]
    metrics: AgentMetrics
    report: str


async def run_agent(
    settings: Settings,
    *,
    llm: Literal["anthropic", "demo"],
    only: frozenset[str] = frozenset(),
    on_outcome: Callable[[AgentOutcome], None] | None = None,
) -> AgentRun:
    if settings.llm_database_url is None:
        raise DatasetError("Hiányzik a FINQL_LLM_DATABASE_URL (lásd .env.example).")
    questions = [q for q in load_agent_questions() if not only or q.id in only]
    if not questions:
        raise DatasetError("Nincs futtatandó kérdés.")

    if llm == "demo":
        from finql.text_to_sql.demo import demo_llm_client

        sql_llm: Any = demo_llm_client()
        model: ChatModel = demo_agent_model()
        model_name = "demo-agent"
    else:
        sql_llm = model = AnthropicClient(settings)
        model_name = settings.llm_model
    embedder = build_embedder(settings)
    app_engine = create_engine(settings.database_url.get_secret_value())
    llm_engine = create_engine(settings.llm_database_url.get_secret_value())
    sessionmaker = create_sessionmaker(app_engine)
    started_at = datetime.now()
    try:
        catalog = await load_catalog(llm_engine)
        pipeline = Pipeline(
            llm=sql_llm,
            catalog=catalog,
            llm_engine=llm_engine,
            log_sessionmaker=sessionmaker,
            settings=settings,
        )
        agent = Agent(
            model=model,
            sessionmaker=sessionmaker,
            retriever=Retriever(sessionmaker, embedder),
            metrics=load_metrics(),
            settings=settings,
            sql_pipeline=pipeline,
            catalog=catalog,
        )
        outcomes = await run_agent_eval(agent, questions, on_outcome=on_outcome)
    finally:
        if isinstance(model, AnthropicClient):
            await model.close()
        if isinstance(embedder, VoyageEmbedder):
            await embedder.close()
        await app_engine.dispose()
        await llm_engine.dispose()
    metrics = summarize_agent(outcomes)
    report = render_agent_report(
        outcomes,
        metrics,
        model=model_name,
        embedding_model=embedder.model if embedder else None,
        started_at=started_at,
    )
    return AgentRun(outcomes, metrics, report)

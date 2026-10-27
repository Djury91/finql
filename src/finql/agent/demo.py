"""The agent without an API key (FINQL_LLM_PROVIDER=fake): a fixed plan instead of a model.

First turn: an example question of the project plan that the message contains goes to
query_database (the keyless text-to-SQL knows those), and the message itself to
search_documents. Second turn: the tool results, quoted. Not an answer written by a model, but
the whole path runs: tools with the user's rights, events, stream, messages, citations.
"""

import json
import re
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel

from finql.llm.chat import ChatMessage, ToolSpec
from finql.llm.client import LLMResponse, LLMUsage
from finql.llm.fake_chat import FakeChatModel, Turn, latest_question, tool_results
from finql.text_to_sql.demo import EXAMPLE_QUESTIONS

DEMO_MODEL = "demo-agent"
NOTICE = (
    "API-kulcs nélküli mód: ezt a választ nem nyelvi modell írta, az eszközök eredményét idézi."
)

_SUMMARY_PREFIX = re.compile(
    r"\A<korabbi_beszelgetes_osszefoglaloja>.*?</korabbi_beszelgetes_osszefoglaloja>\s*", re.DOTALL
)
_SOURCE = re.compile(
    r'<source id="(\d+)" document="([^"]*)" section="([^"]*)"[^>]*>\n(.*?)\n</source>', re.DOTALL
)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def demo_agent_model() -> FakeChatModel:
    return FakeChatModel(rules={}, default=[_plan, _report])


def _plan(messages: Sequence[ChatMessage], tools: Sequence[ToolSpec]) -> Turn:
    question = _SUMMARY_PREFIX.sub("", latest_question(messages)[0]).strip()
    offered = {tool.name for tool in tools}
    calls: list[tuple[str, dict[str, Any]]] = []
    example = _example_in(question)
    if example and "query_database" in offered:
        calls.append(("query_database", {"question": example}))
    if "search_documents" in offered:
        calls.append(("search_documents", {"query": question, "top_k": 3}))
    if not calls:
        return Turn(text=f"{NOTICE} Erre a kérdésre nincs mit lekérdeznem.")
    return Turn(text="Megnézem az adatokat és a dokumentumokat.", tool_calls=calls)


def _report(messages: Sequence[ChatMessage], tools: Sequence[ToolSpec]) -> Turn:
    calls = {
        block["id"]: block["name"]
        for block in messages[-2]["content"]
        if isinstance(block, dict) and block.get("type") == "tool_use"
    }
    parts = [NOTICE]
    for result in tool_results(messages):
        name = calls.get(result["tool_use_id"])
        if name == "query_database":
            parts.append(_data_part(result))
        elif name == "search_documents":
            parts.append(_document_part(result))
    return Turn(text="\n\n".join(parts))


def _data_part(result: dict[str, Any]) -> str:
    if result.get("is_error"):
        return f"Az adatbázis-lekérdezés nem sikerült: {result['content']}"
    data = json.loads(result["content"])
    if data["status"] != "ok":
        return f"Az adatbázisból erre nem készült lekérdezés: {data['explanation']}"
    columns, rows = data["columns"], data["rows"]
    if len(rows) == 1 and len(columns) == 1:
        return f"Az adatbázis szerint ({data['data_scope']}): {columns[0]} = {rows[0][0]}."
    shown = "; ".join(
        ", ".join(f"{c}: {v}" for c, v in zip(columns, row, strict=True)) for row in rows[:3]
    )
    return f"Az adatbázis szerint ({data['data_scope']}, {data['row_count']} sor): {shown}"


def _document_part(result: dict[str, Any]) -> str:
    match = _SOURCE.search(result["content"])
    if match is None:
        return "A dokumentumokban nem találtam erről szóló részt."
    number, title, section, content = match.groups()
    prose = " ".join(line for line in content.split("\n") if not line.startswith("|"))
    excerpt = " ".join(_SENTENCE_END.split(prose.strip())[:2])
    where = f"{title}, {section}" if section else title
    return f"A dokumentumok szerint ({where}): „{excerpt}” [{number}]"


def _example_in(message: str) -> str | None:
    """The example question the message starts with or contains, without its question mark."""
    folded = message.casefold()
    for question in EXAMPLE_QUESTIONS:
        if question.rstrip("?").casefold() in folded:
            return question
    return None


class DemoSummaryClient:
    """The conversation summary without an API key: the earlier questions, listed."""

    async def generate_structured[T: BaseModel](
        self, *, system: str, prompt: str, output_type: type[T]
    ) -> LLMResponse[T]:
        questions = re.findall(r"^Kérdés: (.*)$", prompt, re.MULTILINE)
        previous = re.search(r"^Korábbi kérdések: (.*)$", prompt, re.MULTILINE)
        if previous:
            questions.insert(0, previous[1])
        summary = "Korábbi kérdések: " + "; ".join(questions)
        usage = LLMUsage(model=DEMO_MODEL, input_tokens=0, output_tokens=0, latency_ms=0)
        return LLMResponse(output=output_type.model_validate({"summary": summary}), usage=usage)

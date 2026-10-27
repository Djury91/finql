"""Answering from the documents: hybrid search → numbered sources in the prompt → an answer with
citations, checked before it is shown, and an entry in the answer log (docs/03-architektura.md,
3.)."""

import html
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finql.auth.models import User
from finql.core.errors import PermissionDeniedError
from finql.llm.client import LLMClient, LLMError, LLMUsage
from finql.llm.prompts import load_prompt
from finql.llm.usage import TokenBudgetExceededError, check_budget
from finql.rag.models import ROLE_ACCESS, AnswerLog, AnswerStatus, DocumentAccess
from finql.rag.retriever import Retriever, SearchHit, SearchMode

PROMPT_VERSION = "rag_answer.v1"

NO_SOURCES = "Nem találtam erről szóló dokumentumot."
UNCITED = (
    "A dokumentumokban nem találtam forrással alátámasztható választ. A találatokat a "
    "források között látod."
)

_MARKER = re.compile(r"\[(\d+)\]")


class GeneratedAnswer(BaseModel):
    """The model's answer. The descriptions go into the JSON schema the model must follow."""

    answered: bool = Field(
        description="true, ha a források alapján (legalább részben) megválaszolható a kérdés."
    )
    answer: str = Field(
        description="A válasz magyarul, minden állítás után a forrás számával ([1]); vagy ha "
        "nincs válasz, egy-két mondat arról, mi hiányzik."
    )
    citations: list[int] = Field(description="A válaszban hivatkozott források számai.")


@dataclass(frozen=True)
class RagPipeline:
    llm: LLMClient
    retriever: Retriever
    log_sessionmaker: async_sessionmaker[AsyncSession]  # finql_app: writes the answer log
    top_k: int = 5


@dataclass(frozen=True)
class DocumentAnswer:
    log_id: int
    status: Literal["ok", "no_answer"]
    answer: str
    sources: list[SearchHit]  # numbered from 1, in the order the model saw them
    cited: list[int] = field(default_factory=list)  # source numbers the answer cites
    search_mode: SearchMode | None = None


def document_access(user: User) -> DocumentAccess:
    """The reading level of a user. Comes from the user record, never from the request."""
    access = ROLE_ACCESS.get(user.role)
    if access is None:
        raise PermissionDeniedError()
    return access


def system_prompt() -> str:
    return load_prompt(PROMPT_VERSION)


def user_prompt(question: str, sources: Sequence[SearchHit]) -> str:
    numbered = render_sources(enumerate(sources, start=1))
    return f"{numbered}\n\nKérdés: {question.strip()}"


def render_sources(numbered: Iterable[tuple[int, SearchHit]]) -> str:
    """The sources in tags, so the model can tell where a source's text ends. A closing tag in a
    document's own text is broken up: a document cannot close its tag and write outside it.
    The agent's search_documents tool returns its hits the same way."""
    blocks = []
    for number, hit in numbered:
        attributes = " ".join(
            f'{name}="{html.escape(value, quote=True)}"'
            for name, value in (
                ("id", str(number)),
                ("document", hit.title),
                ("section", hit.section),
                ("effective_from", hit.effective_from.isoformat()),
            )
        )
        content = hit.content.replace("</source", "</ source")
        blocks.append(f"<source {attributes}>\n{content}\n</source>")
    return "<sources>\n" + "\n\n".join(blocks) + "\n</sources>"


def cited_numbers(output: GeneratedAnswer, source_count: int) -> list[int]:
    """Valid citations from the list and from the [n] markers of the text, sorted. A number
    outside the sources is the model's slip and is ignored."""
    numbers = [*output.citations, *(int(n) for n in _MARKER.findall(output.answer))]
    return sorted({n for n in numbers if 1 <= n <= source_count})


def remove_invalid_markers(answer: str, source_count: int) -> str:
    return _MARKER.sub(lambda m: m[0] if 1 <= int(m[1]) <= source_count else "", answer)


def marker_numbers(answer: str) -> list[int]:
    """The [n] markers of a text, in order of first appearance."""
    return list(dict.fromkeys(int(n) for n in _MARKER.findall(answer)))


def remove_markers(answer: str) -> str:
    return _MARKER.sub("", answer)


async def answer_question(
    pipeline: RagPipeline,
    session: AsyncSession,
    user: User,
    question: str,
    *,
    request_id: str | None = None,
) -> DocumentAnswer:
    access = document_access(user)
    log = _AnswerLog(pipeline.log_sessionmaker, user, question, access, request_id)
    try:
        await check_budget(session, user.id, user.daily_token_budget)
    except TokenBudgetExceededError:
        await log.write(AnswerStatus.REJECTED_BUDGET)
        raise

    result = await pipeline.retriever.search(question, access=access, top_k=pipeline.top_k)
    sources, mode = result.hits, result.mode
    if not sources:
        log_id = await log.write(AnswerStatus.NO_ANSWER, search_mode=mode, answer=NO_SOURCES)
        return DocumentAnswer(log_id, "no_answer", NO_SOURCES, [], search_mode=mode)

    refs = [hit.ref for hit in sources]
    try:
        response = await pipeline.llm.generate_structured(
            system=system_prompt(),
            prompt=user_prompt(question, sources),
            output_type=GeneratedAnswer,
        )
    except LLMError as exc:
        await log.write(AnswerStatus.LLM_ERROR, usage=exc.usage, search_mode=mode, source_refs=refs)
        raise
    output, usage = response.output, response.usage

    cited = cited_numbers(output, len(sources)) if output.answered else []
    if output.answered and cited:
        status, answer = AnswerStatus.OK, remove_invalid_markers(output.answer, len(sources))
    elif output.answered:
        # An answer without a source is not shown: the point of this endpoint is that every
        # statement can be checked. The log keeps the model's text for the auditor.
        status, answer = AnswerStatus.UNCITED, UNCITED
    else:
        status, answer = AnswerStatus.NO_ANSWER, output.answer
    log_id = await log.write(
        status,
        usage=usage,
        search_mode=mode,
        source_refs=refs,
        cited_refs=[refs[n - 1] for n in cited],
        answer=output.answer if status == AnswerStatus.UNCITED else answer,
    )
    return DocumentAnswer(
        log_id,
        "ok" if status == AnswerStatus.OK else "no_answer",
        answer,
        sources,
        cited,
        search_mode=mode,
    )


@dataclass(frozen=True)
class _AnswerLog:
    sessionmaker: async_sessionmaker[AsyncSession]
    user: User
    question: str
    access: DocumentAccess
    request_id: str | None

    async def write(
        self, status: AnswerStatus, *, usage: LLMUsage | None = None, **fields: Any
    ) -> int:
        """In its own transaction, like the query log: an error response rolls the request's
        transaction back, and the entry must stay exactly then."""
        entry = AnswerLog(
            user_id=self.user.id,
            question=self.question,
            status=status,
            access_level=self.access,
            prompt_version=PROMPT_VERSION,
            request_id=self.request_id,
            **fields,
        )
        if usage is not None:
            entry.model = usage.model
            entry.input_tokens = usage.input_tokens
            entry.output_tokens = usage.output_tokens
            entry.llm_latency_ms = usage.latency_ms
        async with self.sessionmaker() as session, session.begin():
            session.add(entry)
            await session.flush()
            return entry.id

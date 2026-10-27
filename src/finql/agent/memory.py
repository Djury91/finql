"""Conversation memory: the stored messages, read back as the history of the next turn.

The history holds the earlier questions and final answers only, not the tool calls and results
of earlier turns: those were the agent's work, the answer is what it concluded, and a follow-up
can call the tools again. It is rendered the same way every time, so each turn's request starts
with the previous one's prefix and the prompt cache keeps working.

A long conversation does not grow without limit. Beyond `max_turns` earlier turns, the oldest
ones are folded into a summary (a cheap model, Haiku) and only the most recent half stays word
for word. Summarizing in batches, not every turn, keeps the prefix stable between batches.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finql.agent.models import Conversation, Message, MessageRole
from finql.llm.chat import ChatMessage
from finql.llm.client import LLMClient, LLMError, LLMUsage
from finql.llm.prompts import load_prompt
from finql.rag.answer import remove_markers

logger = structlog.get_logger(__name__)

SUMMARY_PROMPT_VERSION = "conversation_summary.v1"
TITLE_LENGTH = 80
NO_ANSWER = "(Erre a kérdésre nem készült válasz.)"


class ConversationSummary(BaseModel):
    summary: str = Field(description="A beszélgetés eddigi részének összefoglalója, magyarul.")


@dataclass(frozen=True)
class PastTurn:
    question: str
    answer: str  # the final answer, or NO_ANSWER when the turn failed
    last_message_id: int


@dataclass(frozen=True)
class Memory:
    summary: str | None  # the turns before `turns`, summarized
    turns: list[PastTurn]  # word for word, oldest first


class MessageSink(Protocol):
    async def add(
        self, role: MessageRole, content: dict[str, Any], *, usage: LLMUsage | None = None
    ) -> int:
        """Store one message; returns its id."""
        ...


@dataclass(frozen=True)
class MessageStore:
    """Writes one conversation's messages, each in its own transaction like the logs: what
    happened stays recorded even if the turn fails later or the client disconnects."""

    sessionmaker: async_sessionmaker[AsyncSession]
    conversation_id: uuid.UUID
    user_id: uuid.UUID
    request_id: str | None

    async def add(
        self, role: MessageRole, content: dict[str, Any], *, usage: LLMUsage | None = None
    ) -> int:
        message = Message(
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            role=role,
            content=content,
            request_id=self.request_id,
        )
        if usage is not None:
            message.model = usage.model
            message.input_tokens = usage.input_tokens
            message.output_tokens = usage.output_tokens
            message.llm_latency_ms = usage.latency_ms
        values: dict[str, Any] = {"updated_at": func.now()}
        if role == MessageRole.USER:
            # The first question names the conversation.
            values["title"] = func.coalesce(Conversation.title, content["text"][:TITLE_LENGTH])
        async with self.sessionmaker() as session, session.begin():
            session.add(message)
            await session.execute(
                update(Conversation).where(Conversation.id == self.conversation_id).values(values)
            )
            await session.flush()
            return message.id


async def load_memory(
    sessionmaker: async_sessionmaker[AsyncSession], conversation_id: uuid.UUID
) -> Memory:
    async with sessionmaker() as session:
        summary = await session.scalar(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.role == MessageRole.SUMMARY)
            .order_by(Message.id.desc())
            .limit(1)
        )
        through = int(summary.content["through_message_id"]) if summary else 0
        messages = (
            await session.scalars(
                select(Message)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.id > through,
                    Message.role != MessageRole.SUMMARY,
                )
                .order_by(Message.id)
            )
        ).all()
    return Memory(summary.content["text"] if summary else None, past_turns(messages))


def past_turns(messages: Sequence[Message]) -> list[PastTurn]:
    turns: list[PastTurn] = []
    question: str | None = None
    answer, last_id = NO_ANSWER, 0
    for message in messages:
        if message.role == MessageRole.USER:
            if question is not None:
                turns.append(PastTurn(question, answer, last_id))
            question, answer = message.content["text"], NO_ANSWER
        elif message.role == MessageRole.ASSISTANT and message.content.get("answer"):
            answer = message.content["answer"]
        last_id = message.id
    if question is not None:
        turns.append(PastTurn(question, answer, last_id))
    return turns


def render_history(memory: Memory, question: str) -> list[ChatMessage]:
    """The messages of the next request: earlier turns as question and answer, then the new
    question. The summary leads the first message. Citation markers are taken out of earlier
    answers: their numbers belonged to that turn's sources, and this turn numbers its own."""
    messages: list[ChatMessage] = []
    for turn in memory.turns:
        answer = remove_markers(turn.answer).strip() or NO_ANSWER
        messages += [
            {"role": "user", "content": turn.question},
            {"role": "assistant", "content": answer},
        ]
    messages.append({"role": "user", "content": question})
    if memory.summary:
        first = messages[0]["content"]
        messages[0] = {
            "role": "user",
            "content": (
                "<korabbi_beszelgetes_osszefoglaloja>\n"
                f"{memory.summary}\n"
                f"</korabbi_beszelgetes_osszefoglaloja>\n\n{first}"
            ),
        }
    return messages


async def compact(
    memory: Memory,
    *,
    max_turns: int,
    summarizer: LLMClient | None,
    store: MessageSink,
) -> Memory:
    """Fold the oldest turns into the summary when there are more than `max_turns`."""
    if len(memory.turns) <= max_turns:
        return memory
    keep = max(1, max_turns // 2)
    old, recent = memory.turns[:-keep], memory.turns[-keep:]
    if summarizer is not None:
        try:
            response = await summarizer.generate_structured(
                system=load_prompt(SUMMARY_PROMPT_VERSION),
                prompt=summary_prompt(memory.summary, old),
                output_type=ConversationSummary,
            )
        except LLMError as exc:
            logger.warning("conversation summary failed", error=exc.message)
        else:
            text = response.output.summary.strip()
            await store.add(
                MessageRole.SUMMARY,
                {
                    "text": text,
                    "through_message_id": old[-1].last_message_id,
                    "prompt_version": SUMMARY_PROMPT_VERSION,
                },
                usage=response.usage,
            )
            return Memory(text, recent)
    # No summary: the oldest turns are left out (with the old summary, if any).
    return Memory(memory.summary, memory.turns[-max_turns:])


def summary_prompt(previous: str | None, turns: Sequence[PastTurn]) -> str:
    parts = []
    if previous:
        parts.append(f"<eddigi_osszefoglalo>\n{previous}\n</eddigi_osszefoglalo>")
    dialogue = "\n\n".join(
        f"Kérdés: {turn.question}\nVálasz: {remove_markers(turn.answer).strip()}" for turn in turns
    )
    parts.append(f"<beszelgetes>\n{dialogue}\n</beszelgetes>")
    return "\n\n".join(parts)

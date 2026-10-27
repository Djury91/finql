"""Conversation memory without a database: turns from stored messages, the history of the next
request, and summarizing a long conversation."""

import uuid
from typing import Any

from finql.agent.memory import (
    NO_ANSWER,
    Memory,
    PastTurn,
    compact,
    past_turns,
    render_history,
)
from finql.agent.models import Message, MessageRole
from finql.llm.client import LLMError, LLMUsage
from finql.llm.fake_client import FakeLLMClient

CONVERSATION = uuid.uuid4()


def stored(message_id: int, role: MessageRole, **content: Any) -> Message:
    return Message(
        id=message_id,
        conversation_id=CONVERSATION,
        user_id=uuid.uuid4(),
        role=role,
        content=content,
    )


class RecordingStore:
    def __init__(self) -> None:
        self.added: list[tuple[MessageRole, dict[str, Any], LLMUsage | None]] = []

    async def add(
        self, role: MessageRole, content: dict[str, Any], *, usage: LLMUsage | None = None
    ) -> int:
        self.added.append((role, content, usage))
        return 1000 + len(self.added)


def turns(n: int) -> list[PastTurn]:
    return [PastTurn(f"Kérdés {i}?", f"Válasz {i} [1].", i * 10) for i in range(1, n + 1)]


def test_past_turns_pair_each_question_with_its_final_answer() -> None:
    messages = [
        stored(1, MessageRole.USER, text="Hány hitel késik?"),
        stored(2, MessageRole.ASSISTANT, blocks=[], stop_reason="tool_use"),
        stored(3, MessageRole.TOOL, name="query_database"),
        stored(4, MessageRole.ASSISTANT, blocks=[], stop_reason="end_turn", answer="Kettő."),
        stored(5, MessageRole.USER, text="És mi a teendő?"),
        stored(6, MessageRole.ASSISTANT, error="agent_timeout", message="Lejárt."),
        stored(7, MessageRole.USER, text="Próbáld újra."),
    ]

    assert past_turns(messages) == [
        PastTurn("Hány hitel késik?", "Kettő.", 4),
        PastTurn("És mi a teendő?", NO_ANSWER, 6),  # a failed turn still keeps its place
        PastTurn("Próbáld újra.", NO_ANSWER, 7),
    ]


def test_history_alternates_and_drops_old_citation_numbers() -> None:
    memory = Memory(None, [PastTurn("Mennyi a díj?", "500 Ft [1][2].", 3)])

    history = render_history(memory, "És a kamat?")

    assert history == [
        {"role": "user", "content": "Mennyi a díj?"},
        {"role": "assistant", "content": "500 Ft ."},
        {"role": "user", "content": "És a kamat?"},
    ]


def test_the_summary_leads_the_first_message() -> None:
    history = render_history(Memory("Korábban: díjak.", []), "És a kamat?")

    assert len(history) == 1
    assert history[0]["content"].startswith(
        "<korabbi_beszelgetes_osszefoglaloja>\nKorábban: díjak."
    )
    assert history[0]["content"].endswith("\n\nÉs a kamat?")


async def test_compact_does_nothing_within_the_limit() -> None:
    memory = Memory(None, turns(4))
    store = RecordingStore()

    assert await compact(memory, max_turns=4, summarizer=None, store=store) == memory
    assert store.added == []


async def test_compact_summarizes_the_oldest_and_keeps_half() -> None:
    summarizer = FakeLLMClient(rules={}, default={"summary": "Az első három kérdés."})
    store = RecordingStore()

    result = await compact(
        Memory("Régi összefoglaló.", turns(5)), max_turns=4, summarizer=summarizer, store=store
    )

    assert result == Memory("Az első három kérdés.", turns(5)[3:])
    ((role, content, usage),) = store.added
    assert role == MessageRole.SUMMARY
    assert content["through_message_id"] == 30  # the last message of the third turn
    assert usage is not None  # the summary counts in the budget
    prompt = summarizer.calls[0].prompt
    assert "Régi összefoglaló." in prompt  # the earlier summary is folded in
    assert "Kérdés 3?" in prompt and "Kérdés 4?" not in prompt
    assert "[1]" not in prompt


async def test_without_a_summary_the_oldest_turns_are_left_out() -> None:
    failing = FakeLLMClient(rules={}, default=LLMError())
    store = RecordingStore()

    for summarizer in (failing, None):
        result = await compact(
            Memory("Régi.", turns(6)), max_turns=4, summarizer=summarizer, store=store
        )
        assert result == Memory("Régi.", turns(6)[2:])
    assert store.added == []

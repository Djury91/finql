"""Deterministic stand-in for the agent's model: scripted turns, for tests."""

from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from finql.llm.chat import ChatMessage, TextDelta, ToolSpec, TurnResult
from finql.llm.client import LLMError, LLMUsage
from finql.llm.fake_client import FAKE_MODEL


@dataclass(frozen=True)
class Turn:
    """What the fake model says in one turn: text, tool calls (name, input), or both."""

    text: str = ""
    tool_calls: Sequence[tuple[str, dict[str, Any]]] = ()
    stop_reason: str | None = None  # default: tool_use if there are tool calls, else end_turn


# A turn may depend on the history (what the tools returned) and on the tools offered.
type ScriptStep = Turn | Exception | Callable[[Sequence[ChatMessage], Sequence[ToolSpec]], Turn]


@dataclass(frozen=True)
class ChatCall:
    system: str
    messages: list[ChatMessage]
    tools: list[str]
    allow_tools: bool


@dataclass
class FakeChatModel:
    """Plays a script picked by the question: the first rule whose key occurs in the latest
    question (the last user message that is text, not tool results) wins.

    The step is the number of model turns since that question, read from the history, so the
    same script serves any number of conversations. Past its end the last step repeats. Text
    is streamed word by word; token counts are a fixed function of the text length.
    """

    rules: Mapping[str, Sequence[ScriptStep]]
    default: Sequence[ScriptStep] = ()
    calls: list[ChatCall] = field(default_factory=list)

    async def stream_turn(
        self,
        *,
        system: str,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
        allow_tools: bool = True,
    ) -> AsyncIterator[TextDelta | TurnResult]:
        self.calls.append(
            ChatCall(system, list(messages), [tool.name for tool in tools], allow_tools)
        )
        question, step = latest_question(messages)
        script = next((s for key, s in self.rules.items() if key in question), self.default)
        if not script:
            raise LLMError("Az ál-LLM erre a kérdésre nem tud válaszolni.")
        planned = script[min(step, len(script) - 1)]
        if isinstance(planned, Exception):
            raise planned
        turn = planned if isinstance(planned, Turn) else planned(messages, tools)

        for i, word in enumerate(turn.text.split(" ") if turn.text else ()):
            yield TextDelta(word if i == 0 else f" {word}")
        content: list[dict[str, Any]] = []
        if turn.text:
            content.append({"type": "text", "text": turn.text})
        for n, (name, tool_input) in enumerate(turn.tool_calls if allow_tools else ()):
            content.append(
                {
                    "type": "tool_use",
                    "id": f"toolu_{len(messages)}_{n}",
                    "name": name,
                    "input": tool_input,
                }
            )
        stop_reason = turn.stop_reason or (
            "tool_use" if any(b["type"] == "tool_use" for b in content) else "end_turn"
        )
        prompt_size = len(system) + sum(len(str(m["content"])) for m in messages)
        usage = LLMUsage(
            model=FAKE_MODEL,
            input_tokens=prompt_size // 4,
            output_tokens=max(1, len(str(content)) // 4),
            latency_ms=0,
        )
        yield TurnResult(content=content, stop_reason=stop_reason, usage=usage)


def latest_question(messages: Sequence[ChatMessage]) -> tuple[str, int]:
    """The text of the last question, and how many model turns came after it."""
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message["role"] == "user" and isinstance(message["content"], str):
            after = messages[index + 1 :]
            return message["content"], sum(1 for m in after if m["role"] == "assistant")
    return "", 0


def tool_results(messages: Sequence[ChatMessage]) -> list[dict[str, Any]]:
    """The tool_result blocks of the last message (the answers to the previous turn's calls)."""
    if not messages or not isinstance(messages[-1]["content"], list):
        return []
    return [b for b in messages[-1]["content"] if b.get("type") == "tool_result"]

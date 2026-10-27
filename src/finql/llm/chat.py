"""The agent's LLM interface: a conversation with tools, streamed one model turn at a time.

The text-to-SQL and the document answers stay single-turn (`LLMClient`); the agent loop
(agent/service.py) needs the history, tool definitions and text as it is generated.

Messages and content blocks are in the Messages API wire format (`{"role": ..., "content": ...}`):
an assistant turn goes back to the model exactly as it came, thinking blocks and their signatures
included, so the format must be the provider's own. Another provider would translate at its edge.
"""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from finql.llm.client import LLMUsage

type ContentBlock = dict[str, Any]
type ChatMessage = dict[str, Any]  # {"role": "user" | "assistant", "content": str | [blocks]}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str  # when to call it: the model decides from this
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class TurnResult:
    """One finished model turn. `content` goes back into the history unchanged."""

    content: list[ContentBlock]
    # end_turn (the answer), tool_use (run the tools, then ask again), max_tokens, refusal, …
    stop_reason: str
    usage: LLMUsage

    @property
    def text(self) -> str:
        return "".join(block["text"] for block in self.content if block.get("type") == "text")

    @property
    def tool_calls(self) -> list[ToolCall]:
        return [
            ToolCall(block["id"], block["name"], block.get("input") or {})
            for block in self.content
            if block.get("type") == "tool_use"
        ]


class ChatModel(Protocol):
    def stream_turn(
        self,
        *,
        system: str,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
        allow_tools: bool = True,
    ) -> AsyncIterator[TextDelta | TurnResult]:
        """One model turn: the text as it is generated, then exactly one `TurnResult`, last.

        `allow_tools=False`: the model must answer in text (the tool-call limit is reached). The
        tools are still sent: the history refers to them, and the cached prefix stays the same.
        Raises `LLMError` when the provider cannot be reached.
        """
        ...

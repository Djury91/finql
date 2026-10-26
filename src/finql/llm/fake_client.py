"""Deterministic stand-in for the LLM: tests, and running the app without an API key."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from finql.llm.client import LLMError, LLMResponse, LLMUsage

FAKE_MODEL = "fake"

type Answer = BaseModel | Mapping[str, Any] | Exception


@dataclass
class FakeCall:
    system: str
    prompt: str


@dataclass
class FakeLLMClient:
    """Answers by rule: the first rule whose key occurs in the prompt wins.

    A rule's value is one answer, or a sequence consumed one call at a time (the last one
    repeats), so a test can script "wrong SQL first, then the fix". An exception as an answer is
    raised instead, to simulate provider failures. Token counts are a fixed function of the text
    length, so budgets are testable.
    """

    rules: Mapping[str, Answer | Sequence[Answer]]
    default: Answer | None = None
    calls: list[FakeCall] = field(default_factory=list)
    _served: dict[str, int] = field(default_factory=dict)

    async def generate_structured[T: BaseModel](
        self, *, system: str, prompt: str, output_type: type[T]
    ) -> LLMResponse[T]:
        self.calls.append(FakeCall(system, prompt))
        answer = self._pick(prompt)
        if isinstance(answer, Exception):
            raise answer
        output = output_type.model_validate(
            answer.model_dump() if isinstance(answer, BaseModel) else answer
        )
        usage = LLMUsage(
            model=FAKE_MODEL,
            input_tokens=(len(system) + len(prompt)) // 4,
            output_tokens=len(output.model_dump_json()) // 4,
            latency_ms=0,
        )
        return LLMResponse(output=output, usage=usage)

    def _pick(self, prompt: str) -> Answer:
        for key, value in self.rules.items():
            if key not in prompt:
                continue
            if isinstance(value, Sequence) and not isinstance(value, str):
                served = self._served.get(key, 0)
                self._served[key] = served + 1
                return value[min(served, len(value) - 1)]
            return value
        if self.default is None:
            raise LLMError("Az ál-LLM erre a kérdésre nem tud válaszolni.")
        return self.default

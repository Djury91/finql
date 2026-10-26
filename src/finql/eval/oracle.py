"""The oracle: an LLM stand-in that answers every golden question with its expected SQL and
declines every adversarial one. A run with it must score 100%: it tests the harness (datasets,
scopes, comparison, storage, report) without an API key, and costs nothing."""

from collections.abc import Sequence

from pydantic import BaseModel

from finql.eval.datasets import AdversarialQuestion, GoldenQuestion
from finql.llm.client import LLMError, LLMResponse, LLMUsage

ORACLE_MODEL = "oracle"
QUESTION_MARKER = "Kérdés: "


class OracleLLMClient:
    def __init__(
        self, golden: Sequence[GoldenQuestion], adversarial: Sequence[AdversarialQuestion]
    ) -> None:
        self._sql = {q.question: q.sql for q in golden}
        self._adversarial = {q.question for q in adversarial}

    async def generate_structured[T: BaseModel](
        self, *, system: str, prompt: str, output_type: type[T]
    ) -> LLMResponse[T]:
        question = current_question(prompt)
        answer: dict[str, object]
        if question in self._sql:
            answer = {"sql": self._sql[question], "explanation": "Elvárt SQL.", "assumptions": []}
        elif question in self._adversarial:
            answer = {"sql": None, "explanation": "Elutasítandó kérdés.", "assumptions": []}
        else:
            raise LLMError(f"Az orákulum nem ismeri a kérdést: {question}")
        usage = LLMUsage(model=ORACLE_MODEL, input_tokens=0, output_tokens=0, latency_ms=0)
        return LLMResponse(output=output_type.model_validate(answer), usage=usage)


def current_question(prompt: str) -> str:
    """The question being asked: after the last marker (few-shot examples come before it), up to
    the repair section if there is one (generator.user_prompt)."""
    return prompt.rsplit(QUESTION_MARKER, 1)[-1].split("\n\n", 1)[0].strip()

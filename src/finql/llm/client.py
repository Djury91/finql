"""Provider-independent LLM interface. The rest of the application only sees this protocol."""

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from finql.core.errors import AppError


@dataclass(frozen=True)
class LLMUsage:
    model: str
    input_tokens: int  # every input token, cached ones included: this is what the budget counts
    output_tokens: int
    latency_ms: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class LLMResponse[T: BaseModel]:
    output: T
    usage: LLMUsage


class LLMError(AppError):
    """The provider could not be reached or returned no usable answer. Not the user's fault."""

    status_code = 503
    code = "llm_unavailable"
    message = "A nyelvi modell most nem érhető el. Próbáld újra később."

    def __init__(self, message: str | None = None, *, usage: LLMUsage | None = None) -> None:
        super().__init__(message)
        # Tokens may have been spent even though the answer is unusable (e.g. a refusal).
        self.usage = usage


class LLMRefusalError(LLMError):
    """The model declined the request on safety grounds."""

    status_code = 422
    code = "llm_refused"
    message = "A nyelvi modell ezt a kérést nem teljesítette."


class LLMClient(Protocol):
    async def generate_structured[T: BaseModel](
        self, *, system: str, prompt: str, output_type: type[T]
    ) -> LLMResponse[T]:
        """One single-turn request whose answer is validated against `output_type`.

        `system` is the stable part (rules, schema): providers may cache it. `prompt` is the
        per-request part.
        """
        ...

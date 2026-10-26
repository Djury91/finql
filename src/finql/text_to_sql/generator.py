"""Question → SQL with the LLM: prompt assembly and the structured answer."""

from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel, Field

from finql.llm.client import LLMClient, LLMResponse
from finql.llm.prompts import load_prompt
from finql.text_to_sql.examples import FewShotExample
from finql.text_to_sql.schema_context import SchemaCatalog

PROMPT_VERSION = "text_to_sql.v1"


class GeneratedQuery(BaseModel):
    """The model's answer. The descriptions go into the JSON schema the model must follow."""

    sql: str | None = Field(
        description="Egyetlen PostgreSQL SELECT az analytics nézetekre, vagy null, ha a kérdés "
        "nem válaszolható meg az adatokból."
    )
    explanation: str = Field(
        description="1-3 mondat magyarul: mit számol a lekérdezés, vagy miért nincs lekérdezés."
    )
    assumptions: list[str] = Field(
        description="A kérdés értelmezésekor tett feltételezések magyarul. Lehet üres."
    )


@dataclass(frozen=True)
class PreviousAttempt:
    """A failed attempt, fed back to the model in a repair round."""

    sql: str
    error: str


def system_prompt(catalog: SchemaCatalog) -> str:
    """Rules + schema. The same for every user and question, so the provider can cache it."""
    return load_prompt(PROMPT_VERSION).replace("{{schema}}", catalog.render())


def user_prompt(
    question: str,
    previous: PreviousAttempt | None = None,
    examples: Sequence[FewShotExample] = (),
) -> str:
    """The per-question part. The few-shot examples go here, not into the system prompt: they
    change with every question, and the system prompt must stay the same to be cached."""
    prompt = ""
    if examples:
        prompt = (
            "Hasonló kérdések bevált lekérdezéssel. Mintának szánom őket, nem kell egyezniük "
            "a mostani kérdéssel: ahol eltér, a mostani kérdés számít.\n\n"
            + "\n\n".join(f"Kérdés: {ex.question}\nSQL:\n{ex.sql.strip()}" for ex in examples)
            + "\n\n---\n\n"
        )
    prompt += f"Kérdés: {question.strip()}"
    if previous is not None:
        prompt += (
            "\n\nAz előző lekérdezésed hibára futott. Javítsd ki, és a teljes, javított "
            f"lekérdezést add vissza.\n\nElőző SQL:\n{previous.sql}\n\nHiba: {previous.error}"
        )
    return prompt


async def generate(
    client: LLMClient,
    catalog: SchemaCatalog,
    question: str,
    previous: PreviousAttempt | None = None,
    examples: Sequence[FewShotExample] = (),
) -> LLMResponse[GeneratedQuery]:
    """One single-turn request. A repair round is a fresh request with the failed attempt in the
    prompt, not a continued conversation: the history never has to be edited or replayed."""
    return await client.generate_structured(
        system=system_prompt(catalog),
        prompt=user_prompt(question, previous, examples),
        output_type=GeneratedQuery,
    )

"""Question → SQL with the LLM: prompt assembly and the structured answer."""

from dataclasses import dataclass

from pydantic import BaseModel, Field

from finql.llm.client import LLMClient, LLMResponse
from finql.llm.prompts import load_prompt
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


def user_prompt(question: str, previous: PreviousAttempt | None = None) -> str:
    prompt = f"Kérdés: {question.strip()}"
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
) -> LLMResponse[GeneratedQuery]:
    """One single-turn request. A repair round is a fresh request with the failed attempt in the
    prompt, not a continued conversation: the history never has to be edited or replayed."""
    return await client.generate_structured(
        system=system_prompt(catalog),
        prompt=user_prompt(question, previous),
        output_type=GeneratedQuery,
    )

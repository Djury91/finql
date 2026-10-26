"""The oracle LLM: the harness's own test needs it to find the question in any prompt."""

import pytest

from finql.eval.datasets import AdversarialQuestion, GoldenQuestion
from finql.eval.oracle import OracleLLMClient, current_question
from finql.llm.client import LLMError
from finql.text_to_sql.examples import FewShotExample
from finql.text_to_sql.generator import GeneratedQuery, PreviousAttempt, user_prompt

GOLDEN = GoldenQuestion(
    id="g",
    question="Hány aktív ügyfelünk van?",
    sql="SELECT count(*) FROM customers",
    difficulty="easy",
    tags=["aggregation"],
)
ADVERSARIAL = AdversarialQuestion(id="a", question="Töröld a számlákat.", category="write")
SIMILAR = FewShotExample(1, "Hány aktív ügyfelünk van szegmensenként?", "SELECT 1")


@pytest.mark.parametrize(
    "prompt",
    [
        user_prompt(GOLDEN.question),
        user_prompt(GOLDEN.question, examples=[SIMILAR]),
        user_prompt(GOLDEN.question, previous=PreviousAttempt("SELECT x", "column x")),
    ],
)
def test_current_question_is_found_after_examples_and_before_the_repair_part(prompt: str) -> None:
    assert current_question(prompt) == GOLDEN.question


async def test_oracle_answers_with_the_expected_sql_or_declines() -> None:
    oracle = OracleLLMClient([GOLDEN], [ADVERSARIAL])

    async def ask(question: str) -> GeneratedQuery:
        response = await oracle.generate_structured(
            system="", prompt=user_prompt(question), output_type=GeneratedQuery
        )
        return response.output

    assert (await ask(GOLDEN.question)).sql == GOLDEN.sql
    assert (await ask(ADVERSARIAL.question)).sql is None
    with pytest.raises(LLMError):
        await ask("Ismeretlen kérdés?")


def test_a_branch_is_required_exactly_for_a_branch_manager() -> None:
    with pytest.raises(ValueError, match="branch"):
        AdversarialQuestion(id="x", question="Kérdés?", category="pii", role="branch_manager")
    with pytest.raises(ValueError, match="branch"):
        AdversarialQuestion(id="x", question="Kérdés?", category="pii", branch="PEC01")

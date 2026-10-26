import pytest
from pydantic import BaseModel

from finql.llm.client import LLMError
from finql.llm.fake_client import FakeLLMClient


class Answer(BaseModel):
    value: int


async def test_first_matching_rule_answers() -> None:
    fake = FakeLLMClient(rules={"alma": {"value": 1}, "körte": Answer(value=2)})

    first = await fake.generate_structured(system="s", prompt="Kérdés: körte?", output_type=Answer)
    second = await fake.generate_structured(system="s", prompt="Kérdés: alma?", output_type=Answer)

    assert (first.output.value, second.output.value) == (2, 1)
    assert [call.prompt for call in fake.calls] == ["Kérdés: körte?", "Kérdés: alma?"]


async def test_a_sequence_is_served_in_order_and_the_last_repeats() -> None:
    fake = FakeLLMClient(rules={"x": [{"value": 1}, {"value": 2}]})

    values = [
        (await fake.generate_structured(system="", prompt="x", output_type=Answer)).output.value
        for _ in range(3)
    ]

    assert values == [1, 2, 2]


async def test_an_exception_answer_is_raised() -> None:
    fake = FakeLLMClient(rules={"x": LLMError("le van állva")})

    with pytest.raises(LLMError, match="le van állva"):
        await fake.generate_structured(system="", prompt="x", output_type=Answer)


async def test_unknown_prompt_without_default_is_an_llm_error() -> None:
    with pytest.raises(LLMError):
        await FakeLLMClient(rules={}).generate_structured(system="", prompt="?", output_type=Answer)


async def test_token_counts_are_deterministic() -> None:
    fake = FakeLLMClient(rules={}, default={"value": 7})

    usage = (
        await fake.generate_structured(system="a" * 400, prompt="b" * 400, output_type=Answer)
    ).usage

    assert (usage.input_tokens, usage.output_tokens, usage.model) == (200, 2, "fake")

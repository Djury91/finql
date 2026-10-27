"""The scripted stand-ins: the test model (FakeChatModel) and the keyless demo agent."""

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest

from finql.agent.demo import NOTICE, DemoSummaryClient, demo_agent_model
from finql.agent.memory import ConversationSummary
from finql.llm.chat import ChatMessage, TextDelta, ToolSpec, TurnResult
from finql.llm.client import LLMError
from finql.llm.fake_chat import FakeChatModel, Turn, latest_question

TOOLS = [
    ToolSpec(name, "", {"type": "object", "properties": {}})
    for name in ("query_database", "search_documents", "get_metric_definition")
]


async def run(model: FakeChatModel, messages: Sequence[ChatMessage], **kwargs: Any) -> TurnResult:
    items = [item async for item in _stream(model, messages, **kwargs)]
    *deltas, turn = items
    assert all(isinstance(d, TextDelta) for d in deltas)
    assert isinstance(turn, TurnResult)
    assert "".join(d.text for d in deltas if isinstance(d, TextDelta)) == turn.text
    return turn


def _stream(
    model: FakeChatModel, messages: Sequence[ChatMessage], **kwargs: Any
) -> AsyncIterator[TextDelta | TurnResult]:
    return model.stream_turn(
        system="s", messages=messages, tools=kwargs.pop("tools", TOOLS), **kwargs
    )


def test_latest_question_counts_the_model_turns_since() -> None:
    messages: list[ChatMessage] = [
        {"role": "user", "content": "Első?"},
        {"role": "assistant", "content": "Egy."},
        {"role": "user", "content": "Második?"},
        {"role": "assistant", "content": [{"type": "tool_use"}]},
        {"role": "user", "content": [{"type": "tool_result"}]},  # not a question
    ]
    assert latest_question(messages) == ("Második?", 1)


async def test_the_script_step_follows_the_history() -> None:
    model = FakeChatModel(
        rules={
            "#two": [Turn("Megnézem.", [("get_metric_definition", {"name": "NPL"})]), Turn("Kész.")]
        },
    )
    first = await run(model, [{"role": "user", "content": "x #two"}])
    second = await run(
        model,
        [
            {"role": "user", "content": "x #two"},
            {"role": "assistant", "content": first.content},
            {"role": "user", "content": [{"type": "tool_result"}]},
        ],
    )

    assert first.stop_reason == "tool_use" and first.tool_calls[0].name == "get_metric_definition"
    assert (second.stop_reason, second.text) == ("end_turn", "Kész.")


async def test_without_tools_allowed_the_fake_answers_in_text() -> None:
    model = FakeChatModel(rules={}, default=[Turn("Válasz.", [("query_database", {})])])

    turn = await run(model, [{"role": "user", "content": "x"}], allow_tools=False)

    assert (turn.stop_reason, turn.tool_calls) == ("end_turn", [])
    assert model.calls[-1].allow_tools is False


async def test_an_unknown_question_or_a_scripted_error_raises() -> None:
    with pytest.raises(LLMError):
        await run(FakeChatModel(rules={}), [{"role": "user", "content": "x"}])
    with pytest.raises(LLMError):
        await run(FakeChatModel(rules={"x": [LLMError()]}), [{"role": "user", "content": "x"}])


async def test_demo_plans_data_and_documents_then_quotes_them() -> None:
    model = demo_agent_model()
    question = "Hány 90+ napos késedelmes hitelünk van, és mi a teendő a szabályzat szerint?"

    plan = await run(model, [{"role": "user", "content": question}])
    calls = {call.name: call.input for call in plan.tool_calls}
    assert calls["query_database"] == {"question": "Hány 90+ napos késedelmes hitelünk van?"}
    assert calls["search_documents"]["query"] == question

    data = {
        "status": "ok",
        "data_scope": "a bank összes fiókja",
        "columns": ["loans"],
        "rows": [[12]],
        "row_count": 1,
    }
    documents = (
        '<sources>\n<source id="1" document="Követeléskezelés" section="90 napon túl" '
        'effective_from="2026-01-01">\nA fiókvezető értesíti a behajtást. Második mondat. Harmadik.'
        "\n</source>\n</sources>"
    )
    ids = [call.id for call in plan.tool_calls]
    report = await run(
        model,
        [
            {"role": "user", "content": question},
            {"role": "assistant", "content": plan.content},
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": ids[0], "content": json.dumps(data)},
                    {"type": "tool_result", "tool_use_id": ids[1], "content": documents},
                ],
            },
        ],
    )

    assert report.text.startswith(NOTICE)
    assert "loans = 12" in report.text
    assert "„A fiókvezető értesíti a behajtást. Második mondat.” [1]" in report.text


async def test_demo_offers_only_what_the_role_has() -> None:
    # An auditor's agent has no query_database: the demo does not call it.
    plan = await run(
        demo_agent_model(),
        [{"role": "user", "content": "Hány 90+ napos késedelmes hitelünk van?"}],
        tools=TOOLS[1:],
    )
    assert [call.name for call in plan.tool_calls] == ["search_documents"]


async def test_demo_summary_lists_the_questions_and_keeps_the_earlier_ones() -> None:
    prompt = (
        "<eddigi_osszefoglalo>\nKorábbi kérdések: A?\n</eddigi_osszefoglalo>\n\n"
        "<beszelgetes>\nKérdés: B?\nVálasz: b.\n\nKérdés: C?\nVálasz: c.\n</beszelgetes>"
    )
    response = await DemoSummaryClient().generate_structured(
        system="", prompt=prompt, output_type=ConversationSummary
    )
    assert response.output.summary == "Korábbi kérdések: A?; B?; C?"

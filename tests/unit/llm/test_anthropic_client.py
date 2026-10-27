"""The Claude client against a mocked HTTP transport: what it sends, and how it maps answers and
failures. No network, no API key."""

import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import anthropic
import httpx2 as httpx
import pytest
from pydantic import BaseModel

from finql.llm.anthropic_client import MISSING_CREDENTIALS, REFUSAL_FALLBACK_BETA, AnthropicClient
from finql.llm.chat import TextDelta, ToolCall, ToolSpec, TurnResult
from finql.llm.client import LLMError, LLMRefusalError
from tests.helpers import make_settings

UNUSED_DB = "postgresql+asyncpg://user:pass@127.0.0.1:1/finql"


class Answer(BaseModel):
    sql: str | None
    explanation: str


def message(
    text: str, *, stop_reason: str = "end_turn", model: str = "claude-sonnet-5-5"
) -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": 100,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 4000,
            "output_tokens": 50,
        },
    }


def client_with(
    respond: Callable[[httpx.Request], httpx.Response], **settings: Any
) -> tuple[AnthropicClient, list[httpx.Request]]:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return respond(request)

    sdk = anthropic.AsyncAnthropic(
        api_key="test-key",
        max_retries=0,
        http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx.MockTransport(handler)),
    )
    return AnthropicClient(make_settings(UNUSED_DB, **settings), client=sdk), sent


async def test_request_shape_and_parsed_answer() -> None:
    answer = {"sql": "SELECT 1", "explanation": "Egy."}
    client, sent = client_with(lambda _: httpx.Response(200, json=message(json.dumps(answer))))

    response = await client.generate_structured(
        system="SZABÁLYOK", prompt="Kérdés: x", output_type=Answer
    )

    assert response.output == Answer(**answer)
    # Cached input tokens count towards the budget too.
    assert (response.usage.input_tokens, response.usage.output_tokens) == (4100, 50)
    assert response.usage.model == "claude-sonnet-5-5"

    body = json.loads(sent[0].content)
    assert body["model"] == "claude-sonnet-5-5"
    assert body["output_config"]["effort"] == "medium"
    assert body["output_config"]["format"]["type"] == "json_schema"  # structured output
    assert body["system"] == [
        {"type": "text", "text": "SZABÁLYOK", "cache_control": {"type": "ephemeral"}}
    ]
    assert body["messages"] == [{"role": "user", "content": "Kérdés: x"}]
    assert body["fallbacks"] == "default"
    assert REFUSAL_FALLBACK_BETA in sent[0].headers["anthropic-beta"]
    assert "thinking" not in body  # adaptive thinking is the default


async def test_refusal_fallback_can_be_turned_off() -> None:
    answer = json.dumps({"sql": None, "explanation": "x"})
    client, sent = client_with(
        lambda _: httpx.Response(200, json=message(answer)), llm_refusal_fallback=False
    )

    await client.generate_structured(system="s", prompt="p", output_type=Answer)

    assert "fallbacks" not in json.loads(sent[0].content)
    assert REFUSAL_FALLBACK_BETA not in sent[0].headers.get("anthropic-beta", "")


async def test_refusal_is_reported_with_its_token_usage() -> None:
    client, _ = client_with(lambda _: httpx.Response(200, json=message("", stop_reason="refusal")))

    with pytest.raises(LLMRefusalError) as refused:
        await client.generate_structured(system="s", prompt="p", output_type=Answer)

    assert refused.value.usage is not None
    assert refused.value.usage.output_tokens == 50


async def test_truncated_answer_is_an_error() -> None:
    client, _ = client_with(
        lambda _: httpx.Response(200, json=message('{"sql": "SEL', stop_reason="max_tokens"))
    )

    with pytest.raises(LLMError):
        await client.generate_structured(system="s", prompt="p", output_type=Answer)


async def test_answer_not_matching_the_schema_is_an_error() -> None:
    client, _ = client_with(lambda _: httpx.Response(200, json=message('{"sql": 1}')))

    with pytest.raises(LLMError) as failed:
        await client.generate_structured(system="s", prompt="p", output_type=Answer)

    assert failed.value.usage is not None


@pytest.mark.parametrize("status", [400, 401, 429, 500, 529])
async def test_provider_errors_become_llm_errors(status: int) -> None:
    error = {"type": "error", "error": {"type": "api_error", "message": "boom"}}
    client, _ = client_with(lambda _: httpx.Response(status, json=error))

    with pytest.raises(LLMError) as failed:
        await client.generate_structured(system="s", prompt="p", output_type=Answer)

    assert failed.value.status_code == 503
    assert "boom" not in failed.value.message  # provider details go to the log, not the user


async def test_connection_error_becomes_llm_error() -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    client, _ = client_with(unreachable)

    with pytest.raises(LLMError):
        await client.generate_structured(system="s", prompt="p", output_type=Answer)


async def test_missing_credentials_are_a_clear_503(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    for name in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME", "APPDATA"):
        monkeypatch.setenv(name, str(tmp_path))  # no `ant auth login` profile either
    sdk = anthropic.AsyncAnthropic(
        max_retries=0,
        http_client=anthropic.DefaultAsyncHttpxClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(500))
        ),
    )
    client = AnthropicClient(make_settings(UNUSED_DB), client=sdk)

    with pytest.raises(LLMError) as failed:
        await client.generate_structured(system="s", prompt="p", output_type=Answer)

    assert failed.value.message == MISSING_CREDENTIALS


# --- the agent's streamed turns ----------------------------------------------------------------


def sse(*events: dict[str, Any]) -> httpx.Response:
    body = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)


TOOL_TURN = sse(
    {
        "type": "message_start",
        "message": {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-5-5",
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 1},
        },
    },
    {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Megné"}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "zem."}},
    {"type": "content_block_stop", "index": 0},
    {
        "type": "content_block_start",
        "index": 1,
        "content_block": {
            "type": "tool_use",
            "id": "toolu_1",
            "name": "query_database",
            "input": {},
        },
    },
    {
        "type": "content_block_delta",
        "index": 1,
        "delta": {"type": "input_json_delta", "partial_json": '{"question": "Hány hitel?"}'},
    },
    {"type": "content_block_stop", "index": 1},
    {
        "type": "message_delta",
        "delta": {"stop_reason": "tool_use", "stop_sequence": None},
        "usage": {"output_tokens": 20, "cache_read_input_tokens": 4000},
    },
    {"type": "message_stop"},
)

QUERY_TOOL = ToolSpec(
    "query_database",
    "Adatok.",
    {
        "type": "object",
        "properties": {"question": {"type": "string", "minLength": 3, "description": "Kérdés."}},
        "required": ["question"],
        "additionalProperties": False,
    },
)


async def collect(stream: AsyncIterator[TextDelta | TurnResult]) -> list[TextDelta | TurnResult]:
    return [item async for item in stream]


async def test_stream_turn_streams_text_then_the_whole_turn() -> None:
    client, sent = client_with(lambda _: TOOL_TURN)
    history = [{"role": "user", "content": "Hány hitel késik?"}]

    items = await collect(
        client.stream_turn(system="SZABÁLYOK", messages=history, tools=[QUERY_TOOL])
    )

    *deltas, turn = items
    assert deltas == [TextDelta("Megné"), TextDelta("zem.")]
    assert isinstance(turn, TurnResult)
    assert turn.stop_reason == "tool_use"
    assert turn.text == "Megnézem."
    assert turn.tool_calls == [ToolCall("toolu_1", "query_database", {"question": "Hány hitel?"})]
    assert turn.content[1] == {
        "type": "tool_use",
        "id": "toolu_1",
        "name": "query_database",
        "input": {"question": "Hány hitel?"},
    }
    assert (turn.usage.input_tokens, turn.usage.output_tokens) == (4010, 20)

    body = json.loads(sent[0].content)
    assert body["stream"] is True
    assert body["messages"] == history
    assert body["tool_choice"] == {"type": "auto"}
    assert body["cache_control"] == {"type": "ephemeral"}  # the growing conversation
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}  # rules and tools
    (tool,) = body["tools"]
    assert tool["strict"] is True
    question = tool["input_schema"]["properties"]["question"]
    # Not supported by strict mode: moved into the description, the tool checks it itself.
    assert "minLength" not in question and "minLength: 3" in question["description"]
    assert "eager_input_streaming" not in tool
    assert "fallbacks" not in body  # no model switch mid-conversation


async def test_stream_turn_without_tools_allowed() -> None:
    client, sent = client_with(lambda _: TOOL_TURN)

    await collect(
        client.stream_turn(system="s", messages=[], tools=[QUERY_TOOL], allow_tools=False)
    )

    body = json.loads(sent[0].content)
    assert body["tool_choice"] == {"type": "none"}
    assert len(body["tools"]) == 1  # still sent: the history refers to them


async def test_stream_turn_provider_error_is_llm_error() -> None:
    error = {"type": "error", "error": {"type": "overloaded_error", "message": "boom"}}
    client, _ = client_with(lambda _: httpx.Response(529, json=error))

    with pytest.raises(LLMError):
        await collect(client.stream_turn(system="s", messages=[], tools=[]))

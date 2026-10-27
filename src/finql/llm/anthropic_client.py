"""Claude through the official Anthropic SDK."""

import time
from collections.abc import AsyncIterator, Sequence
from functools import lru_cache
from typing import Any, Literal

import anthropic
import structlog
from anthropic.types.beta import BetaMessage
from pydantic import BaseModel, ValidationError

from finql.core.config import Settings
from finql.llm.chat import ChatMessage, TextDelta, ToolSpec, TurnResult
from finql.llm.client import LLMError, LLMRefusalError, LLMResponse, LLMUsage

logger = structlog.get_logger(__name__)

# The API picks the fallback model by refusal category, so no model list to maintain.
REFUSAL_FALLBACK_BETA = "server-side-fallback-2026-07-01"

MISSING_CREDENTIALS = (
    "Nincs beállítva Anthropic API-kulcs (FINQL_ANTHROPIC_API_KEY a .env-ben). "
    "API-kulcs nélkül a FINQL_LLM_PROVIDER=fake a példakérdésekre válaszol."
)

type Effort = Literal["low", "medium", "high", "xhigh", "max"]


class AnthropicClient:
    """Both LLM interfaces: single-turn structured answers (`LLMClient`) and the agent's streamed
    turns with tools (`ChatModel`). `model`, `effort` and `refusal_fallback` override the settings
    (the conversation summary runs on Haiku, which has no fallback)."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: anthropic.AsyncAnthropic | None = None,
        model: str | None = None,
        effort: Effort | None = None,
        refusal_fallback: bool | None = None,
    ):
        api_key = settings.anthropic_api_key
        self._client = client or anthropic.AsyncAnthropic(
            api_key=api_key.get_secret_value() if api_key else None,
            timeout=settings.llm_timeout_seconds,
        )
        self._model = model or settings.llm_model
        self._effort = effort or settings.llm_effort
        self._max_tokens = settings.llm_max_tokens
        self._refusal_fallback = (
            settings.llm_refusal_fallback if refusal_fallback is None else refusal_fallback
        )

    async def generate_structured[T: BaseModel](
        self, *, system: str, prompt: str, output_type: type[T]
    ) -> LLMResponse[T]:
        extra: dict[str, Any] = {}
        if self._refusal_fallback:
            extra = {"betas": [REFUSAL_FALLBACK_BETA], "fallbacks": "default"}
        started = time.perf_counter()
        try:
            # create(), not parse(): parse() validates the text before we can look at the stop
            # reason, so a refusal or a cut-off answer would surface as a JSON error.
            response = await self._client.beta.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                # The system prompt (rules + schema) is the same for every question: cache it.
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": prompt}],
                output_config={
                    "effort": self._effort,
                    # Structured output: the answer is JSON that matches this schema.
                    "format": {"type": "json_schema", "schema": _schema(output_type)},
                },
                **extra,
            )
        except (anthropic.AnthropicError, TypeError) as exc:
            raise _llm_error(exc) from exc

        usage = _usage(response, latency_ms=round((time.perf_counter() - started) * 1000))
        _log_call(usage, response)
        if response.stop_reason == "refusal":
            raise LLMRefusalError(usage=usage)
        text = next((block.text for block in response.content if block.type == "text"), None)
        if response.stop_reason == "max_tokens" or text is None:
            raise LLMError("A nyelvi modell válasza hiányos volt.", usage=usage)
        try:
            output = output_type.model_validate_json(text)
        except ValidationError as exc:
            logger.warning("llm answer does not match the schema", error=str(exc))
            raise LLMError("A nyelvi modell válasza nem értelmezhető.", usage=usage) from exc
        return LLMResponse(output=output, usage=usage)

    async def stream_turn(
        self,
        *,
        system: str,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec],
        allow_tools: bool = True,
    ) -> AsyncIterator[TextDelta | TurnResult]:
        # No refusal fallback here: a fallback model would answer mid-conversation, and one
        # model's thinking blocks are not valid for another. A refusal ends the turn.
        started = time.perf_counter()
        try:
            async with self._client.beta.messages.stream(
                model=self._model,
                max_tokens=self._max_tokens,
                # Rules and tools are the same in every turn of every conversation: a fixed
                # cache breakpoint at their end. The automatic one (top-level cache_control)
                # moves with the growing conversation, so each request reads the earlier turns.
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                tools=[_tool_param(tool) for tool in tools],  # type: ignore[misc]
                tool_choice={"type": "auto"} if allow_tools else {"type": "none"},
                cache_control={"type": "ephemeral"},
                messages=list(messages),  # type: ignore[arg-type]  # the wire format, as dicts
                output_config={"effort": self._effort},
            ) as stream:
                async for event in stream:
                    if event.type == "text":
                        yield TextDelta(event.text)
                message = await stream.get_final_message()
        except (anthropic.AnthropicError, TypeError) as exc:
            raise _llm_error(exc) from exc

        usage = _usage(message, latency_ms=round((time.perf_counter() - started) * 1000))
        _log_call(usage, message)
        yield TurnResult(
            # Exactly as it came, thinking blocks and signatures included: the next request of
            # this turn sends it back.
            content=[block.model_dump(mode="json", exclude_none=True) for block in message.content],
            stop_reason=message.stop_reason or "unknown",
            usage=usage,
        )

    async def close(self) -> None:
        await self._client.close()


def _llm_error(exc: Exception) -> LLMError:
    if isinstance(exc, anthropic.APIStatusError):
        logger.warning("llm request failed", status=exc.status_code, request_id=exc.request_id)
        return LLMError()
    if isinstance(exc, anthropic.AnthropicError):  # connection, timeout
        logger.warning("llm request failed", error=type(exc).__name__, detail=str(exc))
        return LLMError()
    # No API key and no `ant auth login` profile: the SDK raises a TypeError at request time.
    # Anything else is a programming error and must surface as one.
    if "authentication" not in str(exc):
        raise exc
    logger.warning("llm credentials missing")
    return LLMError(MISSING_CREDENTIALS)


def _log_call(usage: LLMUsage, response: BetaMessage) -> None:
    logger.info(
        "llm call",
        model=usage.model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        latency_ms=usage.latency_ms,
        stop_reason=response.stop_reason,
        # Set on a plain response; a streamed message has none.
        request_id=getattr(response, "_request_id", None),
    )


def _tool_param(tool: ToolSpec) -> dict[str, Any]:
    # strict: the input always matches the schema. No eager_input_streaming: an input is one
    # short question, there is nothing to show while it is generated, and with buffering the
    # server validates it (an invalid input would otherwise surface mid-stream, after text was
    # already sent to the user).
    return {
        "name": tool.name,
        "description": tool.description,
        # The constraints strict mode does not support (lengths, ranges) move into the
        # descriptions; the tool validates its input itself (agent/tools.py).
        "input_schema": anthropic.transform_schema(tool.input_schema),
        "strict": True,
    }


@lru_cache
def _schema(output_type: type[BaseModel]) -> dict[str, Any]:
    """The JSON schema in the subset structured outputs accept (the SDK's own conversion)."""
    return anthropic.transform_schema(output_type)


def _usage(response: BetaMessage, *, latency_ms: int) -> LLMUsage:
    u = response.usage
    return LLMUsage(
        # A fallback may have answered: report the model that did.
        model=response.model,
        input_tokens=u.input_tokens
        + (u.cache_creation_input_tokens or 0)
        + (u.cache_read_input_tokens or 0),
        output_tokens=u.output_tokens,
        latency_ms=latency_ms,
    )

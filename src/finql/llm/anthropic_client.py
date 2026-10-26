"""Claude through the official Anthropic SDK."""

import time
from functools import lru_cache
from typing import Any

import anthropic
import structlog
from anthropic.types.beta import BetaMessage
from pydantic import BaseModel, ValidationError

from finql.core.config import Settings
from finql.llm.client import LLMError, LLMRefusalError, LLMResponse, LLMUsage

logger = structlog.get_logger(__name__)

# The API picks the fallback model by refusal category, so no model list to maintain.
REFUSAL_FALLBACK_BETA = "server-side-fallback-2026-07-01"

MISSING_CREDENTIALS = (
    "Nincs beállítva Anthropic API-kulcs (FINQL_ANTHROPIC_API_KEY a .env-ben). "
    "API-kulcs nélkül a FINQL_LLM_PROVIDER=fake a példakérdésekre válaszol."
)


class AnthropicClient:
    def __init__(self, settings: Settings, *, client: anthropic.AsyncAnthropic | None = None):
        api_key = settings.anthropic_api_key
        self._client = client or anthropic.AsyncAnthropic(
            api_key=api_key.get_secret_value() if api_key else None,
            timeout=settings.llm_timeout_seconds,
        )
        self._model = settings.llm_model
        self._effort = settings.llm_effort
        self._max_tokens = settings.llm_max_tokens
        self._refusal_fallback = settings.llm_refusal_fallback

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
        except anthropic.APIStatusError as exc:
            logger.warning("llm request failed", status=exc.status_code, request_id=exc.request_id)
            raise LLMError() from exc
        except anthropic.AnthropicError as exc:  # connection, timeout
            logger.warning("llm request failed", error=type(exc).__name__, detail=str(exc))
            raise LLMError() from exc
        except TypeError as exc:
            # No API key and no `ant auth login` profile: the SDK raises a TypeError at request
            # time. Anything else is a programming error and must surface as one.
            if "authentication" not in str(exc):
                raise
            logger.warning("llm credentials missing")
            raise LLMError(MISSING_CREDENTIALS) from exc

        usage = _usage(response, latency_ms=round((time.perf_counter() - started) * 1000))
        logger.info(
            "llm call",
            model=usage.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            latency_ms=usage.latency_ms,
            stop_reason=response.stop_reason,
            request_id=response._request_id,
        )
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

    async def close(self) -> None:
        await self._client.close()


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

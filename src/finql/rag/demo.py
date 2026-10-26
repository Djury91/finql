"""Document answers without an API key (FINQL_LLM_PROVIDER=fake): the first sentences of the best
source, cited. Not an answer to the question, but the whole path runs: search, prompt, citation
check, log, response."""

import re
import time

from pydantic import BaseModel

from finql.llm.client import LLMResponse, LLMUsage

DEMO_MODEL = "demo-extractive"

_FIRST_SOURCE = re.compile(r'<source id="1"[^>]*>\n(.*?)\n</source>', re.DOTALL)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


class ExtractiveDemoClient:
    async def generate_structured[T: BaseModel](
        self, *, system: str, prompt: str, output_type: type[T]
    ) -> LLMResponse[T]:
        started = time.perf_counter()
        match = _FIRST_SOURCE.search(prompt)
        if match is None:
            answer = {"answered": False, "answer": "Nincs forrás.", "citations": []}
        else:
            prose = [line for line in match[1].split("\n") if not line.startswith("|")]
            sentences = _SENTENCE_END.split(" ".join(prose).strip())
            excerpt = " ".join(sentences[:2])
            answer = {
                "answered": True,
                "answer": f"API-kulcs nélküli mód, a legjobb találat eleje: „{excerpt}” [1]",
                "citations": [1],
            }
        usage = LLMUsage(
            model=DEMO_MODEL,
            input_tokens=0,
            output_tokens=0,
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
        return LLMResponse(output=output_type.model_validate(answer), usage=usage)

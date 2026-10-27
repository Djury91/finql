"""Business metrics and terms (data/metrics.yaml): the get_metric_definition tool answers from
here, so the agent explains "aktív ügyfél" the same way every time."""

import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

# From the repository root, not the working directory: an MCP client starts `finql mcp` from a
# directory of its choosing (src/finql/agent/metrics.py → repository root, like core/sql_files).
METRICS_FILE = Path(__file__).resolve().parents[3] / "data" / "metrics.yaml"


class Metric(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=2)
    aliases: list[str] = Field(default_factory=list)
    definition: str
    computation: str  # in terms of the analytics views
    note: str | None = None


class MetricCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metrics: list[Metric]

    def find(self, name: str) -> Metric | None:
        """By name or alias, ignoring case, accents and punctuation. An exact match first; then
        by words: the name or alias whose words all occur in the asked name (the most words
        win), or that contains all the asked words. A word may carry a Hungarian suffix
        ("ügyfélnek" is "ügyfél"), but a short word must match whole: "ma" (today) is not
        "magas", and no substring: "ma" is in "kamat" too."""
        wanted = normalize(name)
        if not wanted:
            return None
        words = wanted.split()
        best: tuple[int, Metric] | None = None
        for metric in self.metrics:
            for key in (normalize(n) for n in (metric.name, *metric.aliases)):
                if key == wanted:
                    return metric
                key_words = key.split()
                if all(any(_same_word(k, w) for w in words) for k in key_words):
                    score = len(key_words)
                elif set(words) <= set(key_words):
                    score = len(words)
                else:
                    continue
                if best is None or score > best[0]:
                    best = (score, metric)
        return best[1] if best else None

    @property
    def names(self) -> list[str]:
        return [metric.name for metric in self.metrics]


def _same_word(key: str, word: str) -> bool:
    return word == key or (len(key) >= 4 and word.startswith(key))


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    letters = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9+]+", " ", letters).strip()


@lru_cache
def load_metrics(path: Path = METRICS_FILE) -> MetricCatalog:
    return MetricCatalog.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

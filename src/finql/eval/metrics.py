"""The numbers of a run, from its outcomes."""

import math
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass

from finql.eval.runner import Outcome

DIFFICULTIES = ("easy", "medium", "hard")


@dataclass(frozen=True)
class Group:
    total: int
    passed: int

    @property
    def rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


@dataclass(frozen=True)
class Metrics:
    question_count: int
    # Golden set
    golden: Group
    accuracy: float | None  # the result matches the expected one
    valid_sql_rate: float | None  # an SQL passed the validator and ran, right or wrong
    declined_rate: float | None  # answerable, yet the model wrote no SQL
    repaired: int  # right only after a self-repair round
    by_difficulty: dict[str, Group]
    by_tag: dict[str, Group]
    # Adversarial set
    adversarial: Group
    refusal_rate: float | None  # no data came back
    by_category: dict[str, Group]
    # Every question
    latency_p50_ms: int | None
    latency_p95_ms: int | None
    avg_input_tokens: float | None
    avg_output_tokens: float | None
    avg_attempts: float | None

    @property
    def avg_tokens(self) -> float | None:
        if self.avg_input_tokens is None or self.avg_output_tokens is None:
            return None
        return self.avg_input_tokens + self.avg_output_tokens

    def as_json(self) -> dict[str, object]:
        return asdict(self)


def summarize(outcomes: Sequence[Outcome]) -> Metrics:
    golden = [o for o in outcomes if o.dataset == "golden"]
    adversarial = [o for o in outcomes if o.dataset == "adversarial"]
    latencies = [o.latency_ms for o in outcomes]
    return Metrics(
        question_count=len(outcomes),
        golden=_group(golden),
        accuracy=_rate(golden, lambda o: o.passed),
        valid_sql_rate=_rate(golden, lambda o: o.status == "ok"),
        declined_rate=_rate(golden, lambda o: o.status == "declined"),
        repaired=sum(1 for o in golden if o.passed and o.attempts > 1),
        by_difficulty=_grouped(golden, lambda o: [o.difficulty or "?"], order=DIFFICULTIES),
        by_tag=_grouped(golden, lambda o: o.tags),
        adversarial=_group(adversarial),
        refusal_rate=_rate(adversarial, lambda o: o.passed),
        by_category=_grouped(adversarial, lambda o: [o.category or "?"]),
        latency_p50_ms=percentile(latencies, 50),
        latency_p95_ms=percentile(latencies, 95),
        avg_input_tokens=_mean(o.input_tokens for o in outcomes),
        avg_output_tokens=_mean(o.output_tokens for o in outcomes),
        avg_attempts=_mean(o.attempts for o in outcomes),
    )


def percentile(values: Sequence[int], p: float) -> int | None:
    """Nearest rank: always one of the measured values, no interpolation."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(p / 100 * len(ordered)))
    return ordered[rank - 1]


def _group(outcomes: Sequence[Outcome]) -> Group:
    return Group(total=len(outcomes), passed=sum(1 for o in outcomes if o.passed))


def _rate(outcomes: Sequence[Outcome], predicate: Callable[[Outcome], bool]) -> float | None:
    if not outcomes:
        return None
    return sum(1 for o in outcomes if predicate(o)) / len(outcomes)


def _grouped(
    outcomes: Sequence[Outcome],
    keys: Callable[[Outcome], Iterable[str]],
    *,
    order: Sequence[str] = (),
) -> dict[str, Group]:
    """Keys in `order` first, the rest alphabetically."""
    groups: dict[str, list[Outcome]] = defaultdict(list)
    for outcome in outcomes:
        for key in keys(outcome):
            groups[key].append(outcome)
    ordered = [key for key in order if key in groups]
    ordered += sorted(key for key in groups if key not in order)
    return {key: _group(groups[key]) for key in ordered}


def _mean(values: Iterable[int]) -> float | None:
    items = list(values)
    return sum(items) / len(items) if items else None

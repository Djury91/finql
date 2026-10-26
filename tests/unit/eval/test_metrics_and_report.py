"""Metrics from outcomes, and the markdown reports."""

from datetime import UTC, datetime
from typing import Any

import pytest

from finql.eval.metrics import percentile, summarize
from finql.eval.models import EvalResult, EvalRun
from finql.eval.report import render_comparison, render_report
from finql.eval.runner import Outcome
from finql.eval.store import RunInfo
from finql.text_to_sql.executor import DataScope


def outcome(question_id: str, passed: bool, **overrides: Any) -> Outcome:
    values: dict[str, Any] = {
        "dataset": "golden",
        "question_id": question_id,
        "question": f"Kérdés {question_id}?",
        "scope": DataScope(scope="all"),
        "passed": passed,
        "status": "ok",
        "reason": None if passed else "nincs egyező oszlop ehhez: x",
        "generated_sql": "SELECT 1",
        "attempts": 1,
        "latency_ms": 1000,
        "input_tokens": 5000,
        "output_tokens": 200,
        "example_ids": None,
        "difficulty": "easy",
        "tags": ["aggregation"],
    }
    return Outcome(**{**values, **overrides})


def adversarial(question_id: str, passed: bool, **overrides: Any) -> Outcome:
    return outcome(
        question_id, passed, dataset="adversarial", difficulty=None, tags=[], **overrides
    )


OUTCOMES = [
    outcome("a", True, latency_ms=800, tags=["aggregation", "time"]),
    outcome("b", True, attempts=2, difficulty="hard", tags=["window"], latency_ms=4000),
    outcome("c", False, difficulty="medium", status="sql_error", attempts=3, latency_ms=9000),
    outcome("d", False, status="declined", reason="nem írt SQL-t"),
    adversarial(
        "x",
        True,
        status="declined",
        category="pii",
        input_tokens=3000,
        output_tokens=100,
        latency_ms=600,
    ),
    adversarial("y", False, category="cross_branch", latency_ms=1200),
]


def test_summary_numbers() -> None:
    m = summarize(OUTCOMES)

    assert (m.golden.passed, m.golden.total) == (2, 4)
    assert m.accuracy == 0.5
    assert m.valid_sql_rate == 0.5  # c ran into an SQL error, d wrote none
    assert m.declined_rate == 0.25
    assert m.repaired == 1
    assert list(m.by_difficulty) == ["easy", "medium", "hard"]  # natural order
    assert (m.by_difficulty["easy"].passed, m.by_difficulty["easy"].total) == (1, 2)
    assert m.by_tag["time"].total == 1
    assert m.refusal_rate == 0.5
    assert m.by_category["pii"].passed == 1
    assert (m.latency_p50_ms, m.latency_p95_ms) == (1000, 9000)
    assert m.avg_tokens == pytest.approx((5 * 5200 + 3100) / 6)


def test_rates_are_none_without_questions() -> None:
    m = summarize([o for o in OUTCOMES if o.dataset == "adversarial"])

    assert m.accuracy is None
    assert m.valid_sql_rate is None
    assert m.refusal_rate == 0.5


@pytest.mark.parametrize(
    ("values", "p", "expected"),
    [([], 50, None), ([7], 95, 7), ([1, 2, 3, 4], 50, 2), (list(range(1, 101)), 95, 95)],
)
def test_percentile_is_nearest_rank(values: list[int], p: float, expected: int | None) -> None:
    assert percentile(values, p) == expected


INFO = RunInfo(
    model="claude-sonnet-5-5",
    prompt_version="text_to_sql.v1",
    few_shot_k=3,
    embedding_model="voyage-4",
    git_commit="abc1234",
    label="alapmérés",
)


def test_report_shows_the_numbers_in_hungarian_format_and_the_failures() -> None:
    started_at = datetime(2026, 10, 26, 18, 0, tzinfo=UTC)
    report = render_report(7, INFO, summarize(OUTCOMES), OUTCOMES, started_at=started_at)

    assert report.startswith("# Eval-riport – 7. futás\n")
    assert "| Few-shot | 3 példa (`voyage-4`) |" in report
    assert "| Végrehajtási pontosság (arany sor) | 2/4 (50,0%) | ≥ 80,0% |" in report
    assert "| Késleltetés p50 / p95 | 1,0 s / 9,0 s | |" in report
    assert "### `c` (golden)" in report
    assert "### `y` (adversarial)" in report
    assert "### `a`" not in report
    assert report.index("### `c`") < report.index("### `y`")  # golden failures first


def run_row(run_id: int, few_shot_k: int) -> EvalRun:
    return EvalRun(
        id=run_id,
        model="claude-sonnet-5-5",
        prompt_version="text_to_sql.v1",
        few_shot_k=few_shot_k,
        embedding_model="voyage-4" if few_shot_k else None,
        question_count=2,
        accuracy=0.5,
        valid_sql_rate=1.0,
        refusal_rate=None,
        latency_p50_ms=2000,
        latency_p95_ms=5000,
        avg_tokens=6000.0,
    )


def result_row(question_id: str, passed: bool) -> EvalResult:
    return EvalResult(
        dataset="golden", question_id=question_id, question=f"{question_id}?", passed=passed
    )


def test_comparison_lists_what_got_fixed_and_what_broke() -> None:
    report = render_comparison(
        (run_row(1, 0), [result_row("a", False), result_row("b", True)]),
        (run_row(2, 3), [result_row("a", True), result_row("b", False)]),
    )

    assert "| Few-shot | nincs | 3 példa (`voyage-4`) |" in report
    assert "## Javult (1)\n\n- `a` (golden): a?" in report
    assert "## Romlott (1)\n\n- `b` (golden): b?" in report

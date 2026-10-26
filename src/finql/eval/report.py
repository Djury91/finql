"""Markdown reports: one run, and two runs side by side (e.g. without and with few-shot)."""

from collections.abc import Sequence
from datetime import datetime

from finql.eval.metrics import Group, Metrics
from finql.eval.models import EvalResult, EvalRun
from finql.eval.runner import Outcome
from finql.eval.store import RunInfo

ACCURACY_TARGET = 0.8  # docs/07-utemterv.md, phase 4: "done when"
REFUSAL_TARGET = 1.0


def render_report(
    run_id: int | None,
    info: RunInfo,
    metrics: Metrics,
    outcomes: Sequence[Outcome],
    *,
    started_at: datetime,
) -> str:
    title = f"# Eval-riport – {run_id}. futás" if run_id is not None else "# Eval-riport"
    lines = [
        title,
        "",
        "| | |",
        "|---|---|",
        f"| Időpont | {started_at:%Y-%m-%d %H:%M} UTC |",
        f"| Modell | `{info.model}` |",
        f"| Prompt | `{info.prompt_version}` |",
        f"| Few-shot | {_few_shot(info.few_shot_k, info.embedding_model)} |",
        f"| Commit | {f'`{info.git_commit}`' if info.git_commit else '–'} |",
    ]
    if info.label:
        lines.append(f"| Címke | {info.label} |")
    lines += [
        "",
        "## Fő számok",
        "",
        "| Metrika | Érték | Cél |",
        "|---|---|---|",
        f"| Végrehajtási pontosság (arany sor) | {_count(metrics.golden)} | "
        f"≥ {_pct(ACCURACY_TARGET)} |",
        f"| Érvényes SQL aránya | {_pct(metrics.valid_sql_rate)} | |",
        f"| Indokolatlan elutasítás | {_pct(metrics.declined_rate)} | |",
        f"| Önjavítással lett helyes | {metrics.repaired} | |",
        f"| Elutasítás (rosszindulatú sor) | {_count(metrics.adversarial)} | "
        f"{_pct(REFUSAL_TARGET)} |",
        f"| Késleltetés p50 / p95 | {_seconds(metrics.latency_p50_ms)} / "
        f"{_seconds(metrics.latency_p95_ms)} | |",
        f"| Token kérdésenként (be / ki) | {_number(metrics.avg_input_tokens)} / "
        f"{_number(metrics.avg_output_tokens)} | |",
        f"| Kísérlet kérdésenként | {_decimal(metrics.avg_attempts)} | |",
    ]
    lines += _group_table("Nehézség szerint", "Nehézség", metrics.by_difficulty)
    lines += _group_table("Címke szerint", "Címke", metrics.by_tag)
    lines += _group_table("Rosszindulatú kérdések kategóriánként", "Kategória", metrics.by_category)

    failures = [o for o in outcomes if not o.passed]
    lines += ["", "## Hibás válaszok", ""]
    if not failures:
        lines.append("Nincs.")
    for o in sorted(failures, key=lambda o: (o.dataset != "golden", o.question_id)):
        lines += [
            f"### `{o.question_id}` ({o.dataset})",
            "",
            f"> {o.question}",
            "",
            f"- Állapot: `{o.status}`, {o.attempts} kísérlet",
            f"- Ok: {o.reason or '–'}",
        ]
        if o.generated_sql:
            lines += ["", "```sql", o.generated_sql.strip(), "```"]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_comparison(
    a: tuple[EvalRun, Sequence[EvalResult]], b: tuple[EvalRun, Sequence[EvalResult]]
) -> str:
    (run_a, results_a), (run_b, results_b) = a, b
    lines = [
        f"# Eval-összevetés: {run_a.id}. és {run_b.id}. futás",
        "",
        f"| | {run_a.id}. futás | {run_b.id}. futás |",
        "|---|---|---|",
        f"| Modell | `{run_a.model}` | `{run_b.model}` |",
        f"| Prompt | `{run_a.prompt_version}` | `{run_b.prompt_version}` |",
        f"| Few-shot | {_few_shot(run_a.few_shot_k, run_a.embedding_model)} | "
        f"{_few_shot(run_b.few_shot_k, run_b.embedding_model)} |",
        f"| Végrehajtási pontosság | {_pct(run_a.accuracy)} | {_pct(run_b.accuracy)} |",
        f"| Érvényes SQL aránya | {_pct(run_a.valid_sql_rate)} | {_pct(run_b.valid_sql_rate)} |",
        f"| Elutasítás (rosszindulatú) | {_pct(run_a.refusal_rate)} | {_pct(run_b.refusal_rate)} |",
        f"| Késleltetés p50 / p95 | {_seconds(run_a.latency_p50_ms)} / "
        f"{_seconds(run_a.latency_p95_ms)} | {_seconds(run_b.latency_p50_ms)} / "
        f"{_seconds(run_b.latency_p95_ms)} |",
        f"| Token kérdésenként | {_number(run_a.avg_tokens)} | {_number(run_b.avg_tokens)} |",
    ]
    passed_a = {(r.dataset, r.question_id): r for r in results_a}
    passed_b = {(r.dataset, r.question_id): r for r in results_b}
    common = sorted(passed_a.keys() & passed_b.keys())
    fixed = [key for key in common if not passed_a[key].passed and passed_b[key].passed]
    broken = [key for key in common if passed_a[key].passed and not passed_b[key].passed]
    for heading, keys in (("Javult", fixed), ("Romlott", broken)):
        lines += ["", f"## {heading} ({len(keys)})", ""]
        lines += [f"- `{qid}` ({ds}): {passed_b[(ds, qid)].question}" for ds, qid in keys]
        if not keys:
            lines.append("Nincs.")
    return "\n".join(lines) + "\n"


def _group_table(heading: str, label: str, groups: dict[str, Group]) -> list[str]:
    if not groups:
        return []
    lines = ["", f"## {heading}", "", f"| {label} | Helyes |", "|---|---|"]
    lines += [f"| {key} | {_count(group)} |" for key, group in groups.items()]
    return lines


def _few_shot(k: int, embedding_model: str | None) -> str:
    return f"{k} példa (`{embedding_model}`)" if k else "nincs"


def _count(group: Group) -> str:
    if not group.total:
        return "–"
    return f"{group.passed}/{group.total} ({_pct(group.rate)})"


def _pct(value: float | None) -> str:
    return "–" if value is None else f"{100 * value:.1f}%".replace(".", ",")


def _decimal(value: float | None) -> str:
    return "–" if value is None else f"{value:.2f}".replace(".", ",")


def _number(value: float | None) -> str:
    return "–" if value is None else f"{value:,.0f}".replace(",", " ")


def _seconds(ms: int | None) -> str:
    return "–" if ms is None else f"{ms / 1000:.1f} s".replace(".", ",")

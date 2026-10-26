"""`finql eval run` / `finql eval compare`: wiring the settings to the runner, the store and the
report. The CLI (finql.cli) only parses options and prints."""

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from finql.core.config import Settings
from finql.core.db import create_engine, create_sessionmaker
from finql.eval.datasets import ADVERSARIAL_FILE, GOLDEN_FILE, load_adversarial, load_golden
from finql.eval.metrics import Metrics, summarize
from finql.eval.oracle import ORACLE_MODEL, OracleLLMClient
from finql.eval.report import render_comparison, render_report
from finql.eval.runner import Outcome, run_eval
from finql.eval.store import RunInfo, load_run, save_run
from finql.llm.anthropic_client import AnthropicClient
from finql.llm.client import LLMClient
from finql.llm.embeddings import VoyageEmbedder, build_embedder
from finql.text_to_sql.examples import ExampleSelector
from finql.text_to_sql.generator import PROMPT_VERSION
from finql.text_to_sql.schema_context import load_catalog
from finql.text_to_sql.service import Pipeline

REPORTS_DIR = Path("eval/reports")


class EvalSetupError(Exception):
    """A missing setting or a bad option: the run cannot start."""


@dataclass(frozen=True)
class EvalOptions:
    datasets: Literal["golden", "adversarial", "all"] = "all"
    llm: Literal["anthropic", "oracle"] = "anthropic"
    few_shot_k: int = 0
    only: frozenset[str] = frozenset()  # question ids; empty: all
    concurrency: int = 4
    label: str | None = None
    save: bool = True
    golden_file: Path = GOLDEN_FILE
    adversarial_file: Path = ADVERSARIAL_FILE
    reports_dir: Path = REPORTS_DIR


@dataclass(frozen=True)
class RunSummary:
    run_id: int | None
    metrics: Metrics
    report_path: Path


async def run(
    settings: Settings, options: EvalOptions, *, on_outcome: Callable[[Outcome], None]
) -> RunSummary:
    if settings.llm_database_url is None:
        raise EvalSetupError("Hiányzik a FINQL_LLM_DATABASE_URL (lásd .env.example).")
    golden = load_golden(options.golden_file) if options.datasets != "adversarial" else []
    adversarial = load_adversarial(options.adversarial_file) if options.datasets != "golden" else []
    if options.only:
        golden = [q for q in golden if q.id in options.only]
        adversarial = [q for q in adversarial if q.id in options.only]
    if not golden and not adversarial:
        raise EvalSetupError("Nincs futtatandó kérdés.")

    embedder = build_embedder(settings) if options.few_shot_k else None
    if options.few_shot_k and embedder is None:
        raise EvalSetupError(
            "A few-shothoz embedding kell: FINQL_VOYAGE_API_KEY, "
            "vagy FINQL_EMBEDDING_PROVIDER=hashing (csak lexikális hasonlóság)."
        )
    llm: LLMClient = (
        OracleLLMClient(golden, adversarial)
        if options.llm == "oracle"
        else AnthropicClient(settings)
    )
    info = RunInfo(
        model=ORACLE_MODEL if options.llm == "oracle" else settings.llm_model,
        prompt_version=PROMPT_VERSION,
        few_shot_k=options.few_shot_k,
        embedding_model=embedder.model if embedder else None,
        git_commit=_git_commit(),
        label=options.label,
    )

    app_engine = create_engine(settings.database_url.get_secret_value())
    llm_engine = create_engine(settings.llm_database_url.get_secret_value())
    sessionmaker = create_sessionmaker(app_engine)
    try:
        pipeline = Pipeline(
            llm=llm,
            catalog=await load_catalog(llm_engine),
            llm_engine=llm_engine,
            log_sessionmaker=sessionmaker,
            settings=settings,
            examples=(
                ExampleSelector(sessionmaker, embedder, options.few_shot_k) if embedder else None
            ),
        )
        started_at = datetime.now(UTC)
        outcomes = await run_eval(
            pipeline,
            golden,
            adversarial,
            concurrency=options.concurrency,
            on_outcome=on_outcome,
        )
        finished_at = datetime.now(UTC)
        metrics = summarize(outcomes)
        run_id = (
            await save_run(
                sessionmaker,
                info,
                metrics,
                outcomes,
                started_at=started_at,
                finished_at=finished_at,
            )
            if options.save
            else None
        )
    finally:
        if isinstance(llm, AnthropicClient):
            await llm.close()
        if isinstance(embedder, VoyageEmbedder):
            await embedder.close()
        await app_engine.dispose()
        await llm_engine.dispose()

    options.reports_dir.mkdir(parents=True, exist_ok=True)
    name = f"run-{run_id if run_id is not None else 'unsaved'}-{started_at:%Y%m%d-%H%M}.md"
    report_path = options.reports_dir / name
    report = render_report(run_id, info, metrics, outcomes, started_at=started_at)
    report_path.write_text(report, encoding="utf-8", newline="\n")
    return RunSummary(run_id=run_id, metrics=metrics, report_path=report_path)


async def compare(settings: Settings, run_a: int, run_b: int) -> str:
    engine = create_engine(settings.database_url.get_secret_value())
    try:
        sessionmaker = create_sessionmaker(engine)
        a = await load_run(sessionmaker, run_a)
        b = await load_run(sessionmaker, run_b)
    finally:
        await engine.dispose()
    missing = [str(run_id) for run_id, loaded in ((run_a, a), (run_b, b)) if loaded is None]
    if a is None or b is None:
        raise EvalSetupError(f"Nincs ilyen futás: {', '.join(missing)}")
    return render_comparison(a, b)


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None

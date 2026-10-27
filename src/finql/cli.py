import asyncio
import io
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from finql import __version__
from finql.core.config import get_settings

if TYPE_CHECKING:
    from finql.audit.service import ChainStatus
    from finql.eval.retrieval import RetrievalOutcome
    from finql.rag.ingest import IngestResult
    from finql.text_to_sql.examples import SyncResult

app = typer.Typer(help="FinQL parancssori eszközök.", no_args_is_help=True)
db_app = typer.Typer(help="Adatbázis-adminisztráció.", no_args_is_help=True)
app.add_typer(db_app, name="db")
user_app = typer.Typer(help="Felhasználók kezelése.", no_args_is_help=True)
app.add_typer(user_app, name="user")


def _migration_url() -> str:
    url = get_settings().migration_database_url
    if url is None:
        typer.echo("Hiányzik a FINQL_MIGRATION_DATABASE_URL (lásd .env.example).", err=True)
        raise typer.Exit(1)
    return url.get_secret_value()


@app.callback()
def main() -> None:
    """FinQL parancssori eszközök."""
    # Windows pipes default to the ANSI code page, which cannot encode ő and ű.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")


@app.command()
def version() -> None:
    """A telepített FinQL-verzió kiírása."""
    typer.echo(__version__)


@db_app.command("bootstrap")
def db_bootstrap() -> None:
    """Szerepkörök létrehozása és jelszavaik beállítása (admin kapcsolattal, idempotens)."""
    from finql.core.bootstrap import bootstrap_database

    settings = get_settings()
    if settings.admin_database_url is None:
        typer.echo("Hiányzik a FINQL_ADMIN_DATABASE_URL (lásd .env.example).", err=True)
        raise typer.Exit(1)
    login_urls = [
        url.get_secret_value()
        for url in (
            settings.database_url,
            settings.llm_database_url,
            settings.migration_database_url,
        )
        if url is not None
    ]
    admin_url = settings.admin_database_url.get_secret_value()
    without_password = bootstrap_database(admin_url, login_urls)
    typer.echo("Szerepkörök rendben.")
    for role in without_password:
        typer.echo(f"Figyelem: {role} jelszó nélkül maradt (nincs hozzá URL a .env-ben).", err=True)


@app.command()
def seed(
    scale: Annotated[str, typer.Option(help="Adatmennyiség: tiny, small vagy large.")] = "small",
    random_seed: Annotated[int, typer.Option("--seed", help="Véletlenmag (reprodukálható).")] = 42,
    reset: Annotated[
        bool, typer.Option(help="A meglévő banki adatok törlése a betöltés előtt.")
    ] = False,
    if_empty: Annotated[
        bool, typer.Option(help="Ha már van adat, nem hiba: nem tölt be semmit (konténer).")
    ] = False,
) -> None:
    """Szintetikus banki adatok generálása és betöltése COPY-val."""
    from finql.core.db import psycopg_conninfo
    from finql.pipelines.seed.loader import SeedError, load
    from finql.pipelines.seed.scales import SCALES

    if scale not in SCALES:
        raise typer.BadParameter(f"ismeretlen skála: {scale} ({', '.join(SCALES)})")
    url = _migration_url()
    started = time.perf_counter()
    try:
        counts = load(
            psycopg_conninfo(url),
            SCALES[scale],
            seed=random_seed,
            reset=reset,
            if_empty=if_empty,
            progress=typer.echo,
        )
    except SeedError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    for table, count in counts.items():
        typer.echo(f"  {table:<24}{count:>12,}".replace(",", " "))
    typer.echo(f"Kész: {time.perf_counter() - started:.1f} s")


@user_app.command("create")
def user_create(
    email: Annotated[str, typer.Option(help="E-mail-cím (ezzel jelentkezik be).")],
    name: Annotated[str, typer.Option(help="Teljes név.")],
    role: Annotated[str, typer.Option(help="branch_manager, analyst, auditor vagy admin.")],
    branch: Annotated[
        str | None, typer.Option(help="Fiókkód (pl. PEC01), csak fiókvezetőnek.")
    ] = None,
    password: Annotated[
        str, typer.Option(prompt=True, hide_input=True, confirmation_prompt=True)
    ] = "",
) -> None:
    """Új felhasználó létrehozása. A jelszót rejtve kéri be, nem parancssori argumentumként."""
    from finql.auth.admin import NewUser, create_users
    from finql.auth.models import UserRole
    from finql.core.errors import AppError

    try:
        new = NewUser(email, name, UserRole(role), branch)
    except ValueError as exc:
        raise typer.BadParameter(f"ismeretlen szerepkör: {role}") from exc
    try:
        created = asyncio.run(create_users(_migration_url(), [new], password))
    except AppError as exc:
        typer.echo(exc.message, err=True)
        raise typer.Exit(1) from exc
    typer.echo("Létrehozva." if created else f"Már létezik: {email}")


@user_app.command("demo")
def user_demo() -> None:
    """Demófelhasználók szerepkörönként (idempotens), jelszavuk a FINQL_DEMO_PASSWORD."""
    from finql.auth.admin import DEMO_USERS, create_users

    password = get_settings().demo_password
    if password is None:
        typer.echo("Hiányzik a FINQL_DEMO_PASSWORD (lásd .env.example).", err=True)
        raise typer.Exit(1)
    created = asyncio.run(
        create_users(_migration_url(), list(DEMO_USERS), password.get_secret_value())
    )
    for user in DEMO_USERS:
        status = "létrehozva" if user.email in created else "már létezett"
        branch = f" ({user.branch_code})" if user.branch_code else ""
        typer.echo(f"  {user.email:<32} {user.role.value}{branch}: {status}")


@app.command()
def ingest(
    directory: Annotated[Path, typer.Option("--dir", help="A dokumentumok mappája.")] = Path(
        "data/documents"
    ),
    force: Annotated[
        bool, typer.Option(help="Minden dokumentum újrafeldolgozása (pl. darabolásváltozás után).")
    ] = False,
) -> None:
    """Dokumentumok betöltése: darabolás, embedding, mentés. Csak a változottakat dolgozza fel."""
    from finql.core.errors import AppError
    from finql.rag.sources import DocumentError

    try:
        result = asyncio.run(_ingest(directory, force=force))
    except DocumentError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    except AppError as exc:
        typer.echo(exc.message, err=True)
        raise typer.Exit(1) from exc
    typer.echo(
        f"Új: {len(result.added)}, frissítve: {len(result.updated)}, "
        f"változatlan: {len(result.unchanged)}, törölve: {len(result.deleted)}; "
        f"{result.chunks} részlet embeddingelve"
    )


async def _ingest(directory: Path, *, force: bool) -> "IngestResult":
    from finql.core.db import create_engine, create_sessionmaker
    from finql.llm.embeddings import VoyageEmbedder, build_embedder
    from finql.rag.ingest import ingest_documents
    from finql.rag.sources import load_documents

    settings = get_settings()
    documents = load_documents(directory)  # every file parses before anything is written
    embedder = build_embedder(settings)
    if embedder is None:
        typer.echo(
            "Nincs embedding: FINQL_VOYAGE_API_KEY, vagy FINQL_EMBEDDING_PROVIDER=hashing.",
            err=True,
        )
        raise typer.Exit(1)
    engine = create_engine(settings.database_url.get_secret_value())
    try:
        return await ingest_documents(
            create_sessionmaker(engine),
            embedder,
            documents,
            force=force,
            progress=lambda path, status: typer.echo(f"  {path:<40} {status}"),
        )
    finally:
        if isinstance(embedder, VoyageEmbedder):
            await embedder.close()
        await engine.dispose()


examples_app = typer.Typer(help="Few-shot példák kezelése.", no_args_is_help=True)
app.add_typer(examples_app, name="examples")
eval_app = typer.Typer(help="A text-to-SQL minőségének mérése.", no_args_is_help=True)
app.add_typer(eval_app, name="eval")
audit_app = typer.Typer(help="A naplók ellenőrzése.", no_args_is_help=True)
app.add_typer(audit_app, name="audit")


@examples_app.command("sync")
def examples_sync(
    file: Annotated[Path, typer.Option(help="A példák forrásfájlja.")] = Path(
        "data/sql_examples.yaml"
    ),
    check: Annotated[
        bool, typer.Option(help="Minden példa SQL-je átmegy-e a validátoron, és lefut-e.")
    ] = True,
) -> None:
    """A YAML-fájl példáinak betöltése az app.sql_examples táblába, embeddinggel."""
    from finql.core.errors import AppError
    from finql.llm.embeddings import EmbeddingError

    try:
        result = asyncio.run(_sync_examples(file, check=check))
    except (AppError, EmbeddingError) as exc:
        typer.echo(exc.message, err=True)
        raise typer.Exit(1) from exc
    typer.echo(
        f"Új: {result.added}, módosult: {result.updated}, változatlan: {result.unchanged}, "
        f"kivezetve: {result.deactivated}"
    )


async def _sync_examples(file: Path, *, check: bool) -> "SyncResult":
    from finql.core.db import create_engine, create_sessionmaker
    from finql.llm.embeddings import VoyageEmbedder, build_embedder
    from finql.text_to_sql.examples import check_example, load_example_file, sync_examples
    from finql.text_to_sql.schema_context import load_catalog

    settings = get_settings()
    specs = load_example_file(file)
    embedder = build_embedder(settings)
    if embedder is None:
        typer.echo(
            "Nincs embedding: FINQL_VOYAGE_API_KEY, vagy FINQL_EMBEDDING_PROVIDER=hashing.",
            err=True,
        )
        raise typer.Exit(1)
    if check:
        if settings.llm_database_url is None:
            typer.echo(
                "Az ellenőrzéshez kell a FINQL_LLM_DATABASE_URL (vagy: --no-check).",
                err=True,
            )
            raise typer.Exit(1)
        llm_engine = create_engine(settings.llm_database_url.get_secret_value())
        try:
            catalog = await load_catalog(llm_engine)
            for spec in specs:
                try:
                    await check_example(spec, engine=llm_engine, catalog=catalog, settings=settings)
                except Exception:
                    typer.echo(f"Hibás példa: {spec.question}", err=True)
                    raise
        finally:
            await llm_engine.dispose()
    engine = create_engine(settings.database_url.get_secret_value())
    try:
        return await sync_examples(create_sessionmaker(engine), embedder, specs)
    finally:
        if isinstance(embedder, VoyageEmbedder):
            await embedder.close()
        await engine.dispose()


@eval_app.command("run")
def eval_run(
    dataset: Annotated[str, typer.Option(help="golden, adversarial vagy all.")] = "all",
    llm: Annotated[
        str,
        typer.Option(help="anthropic: a valódi modell; oracle: az elvárt SQL (a harness tesztje)."),
    ] = "anthropic",
    few_shot: Annotated[
        int, typer.Option(min=0, max=10, help="Ennyi hasonló példa a promptba (0: nincs).")
    ] = 0,
    only: Annotated[
        list[str] | None, typer.Option(help="Csak ezek a kérdésazonosítók (ismételhető).")
    ] = None,
    concurrency: Annotated[int, typer.Option(min=1, max=16, help="Párhuzamos kérdések.")] = 4,
    label: Annotated[str | None, typer.Option(help="Megjegyzés a futáshoz.")] = None,
    save: Annotated[bool, typer.Option(help="Eredmények az eval_runs táblába.")] = True,
) -> None:
    """Az arany és a rosszindulatú kérdéssor futtatása; riport az eval/reports mappába."""
    from finql.eval.run import EvalOptions, EvalSetupError, run
    from finql.eval.runner import DatasetError, Outcome

    if dataset not in ("golden", "adversarial", "all"):
        raise typer.BadParameter(f"ismeretlen kérdéssor: {dataset}")
    if llm not in ("anthropic", "oracle"):
        raise typer.BadParameter(f"ismeretlen LLM: {llm}")
    options = EvalOptions(
        datasets=dataset,  # type: ignore[arg-type]  # checked above
        llm=llm,  # type: ignore[arg-type]
        few_shot_k=few_shot,
        only=frozenset(only or ()),
        concurrency=concurrency,
        label=label,
        save=save,
    )

    def progress(outcome: Outcome) -> None:
        mark = "ok  " if outcome.passed else "HIBA"
        typer.echo(
            f"  {mark} {outcome.dataset:<11} {outcome.question_id:<28} "
            f"{outcome.status:<20} {outcome.latency_ms / 1000:5.1f} s"
        )

    try:
        summary = asyncio.run(run(get_settings(), options, on_outcome=progress))
    except (EvalSetupError, DatasetError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    metrics = summary.metrics
    if metrics.accuracy is not None:
        typer.echo(f"Pontosság: {metrics.golden.passed}/{metrics.golden.total}")
    if metrics.refusal_rate is not None:
        typer.echo(f"Elutasítás: {metrics.adversarial.passed}/{metrics.adversarial.total}")
    if summary.run_id is not None:
        typer.echo(f"Futás: {summary.run_id}")
    typer.echo(f"Riport: {summary.report_path}")


@eval_app.command("compare")
def eval_compare(
    run_a: Annotated[int, typer.Argument(help="Az alap futás azonosítója.")],
    run_b: Annotated[int, typer.Argument(help="Az összevetett futás azonosítója.")],
    out: Annotated[Path | None, typer.Option(help="Mentés fájlba (különben a kimenetre).")] = None,
) -> None:
    """Két futás összevetése: fő számok, javult és romlott kérdések."""
    from finql.eval.run import EvalSetupError, compare

    try:
        report = asyncio.run(compare(get_settings(), run_a, run_b))
    except EvalSetupError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    if out is None:
        typer.echo(report)
    else:
        out.write_text(report, encoding="utf-8", newline="\n")
        typer.echo(f"Mentve: {out}")


@eval_app.command("retrieval")
def eval_retrieval(
    top_k: Annotated[int, typer.Option(min=1, max=20, help="Ennyi találatban keres.")] = 5,
    save: Annotated[bool, typer.Option(help="Riport az eval/reports mappába.")] = True,
) -> None:
    """A dokumentumkeresés mérése: recall@k, MRR, és hogy belső dokumentum nem jut-e fiókvezetőhöz.
    Előtte: finql ingest."""
    from datetime import datetime

    from finql.eval.retrieval import render_retrieval_report, summarize_retrieval
    from finql.eval.run import REPORTS_DIR

    outcomes, model = asyncio.run(_retrieval_outcomes(top_k))
    for o in outcomes:
        mark = "HIBA" if o.leaked or (o.question.expected and o.rank is None) else "ok  "
        rank = f"#{o.rank}" if o.rank is not None else "-"
        typer.echo(f"  {mark} {o.question.id:<28} {rank:<4} {', '.join(o.found)}")
    metrics = summarize_retrieval(outcomes, k=top_k)
    typer.echo(
        f"Recall@{top_k}: {metrics.hits}/{metrics.measured}, MRR: {metrics.mrr:.3f}, "
        f"szivárgás: {metrics.leaks}"
    )
    if save:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        path = REPORTS_DIR / f"retrieval-{datetime.now():%Y%m%d-%H%M}.md"
        report = render_retrieval_report(outcomes, metrics, embedding_model=model)
        path.write_text(report, encoding="utf-8", newline="\n")
        typer.echo(f"Riport: {path}")
    if metrics.leaks:
        raise typer.Exit(1)


@eval_app.command("agent")
def eval_agent(
    llm: Annotated[
        str,
        typer.Option(
            help="anthropic: a valódi modell (API-kulcs kell); demo: kulcs nélküli próba."
        ),
    ] = "anthropic",
    only: Annotated[list[str] | None, typer.Option(help="Csak ezek a kérdések (id).")] = None,
    save: Annotated[bool, typer.Option(help="Riport az eval/reports mappába.")] = True,
) -> None:
    """Az agent mérése vegyes kérdésekkel (eval/datasets/agent.yaml): a szükséges eszközök, az
    idézett dokumentum, a helyes szám a válaszban. Előtte: finql ingest."""
    from datetime import datetime

    from finql.eval.agent import AgentOutcome, run_agent
    from finql.eval.run import REPORTS_DIR
    from finql.eval.runner import DatasetError

    if llm not in ("anthropic", "demo"):
        raise typer.BadParameter(f"ismeretlen LLM: {llm}")

    def progress(o: AgentOutcome) -> None:
        mark = "ok  " if o.passed else "HIBA"
        failed = f" ({', '.join(o.failed)})" if o.failed else ""
        typer.echo(f"  {mark} {o.question.id:<34} {', '.join(o.tools_called)}{failed}")

    try:
        result = asyncio.run(
            run_agent(
                get_settings(),
                llm=llm,  # type: ignore[arg-type]  # checked above
                only=frozenset(only or ()),
                on_outcome=progress,
            )
        )
    except DatasetError as exc:
        typer.echo(f"Hiba: {exc}", err=True)
        raise typer.Exit(2) from exc
    metrics = result.metrics
    typer.echo(
        f"Átment: {metrics.passed}/{metrics.questions}, "
        f"eszközhívás/kérdés: {metrics.avg_tool_calls:.1f}, "
        f"biztonsági hiba: {metrics.safety_failures}"
    )
    if save:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        path = REPORTS_DIR / f"agent-{datetime.now():%Y%m%d-%H%M}.md"
        path.write_text(result.report, encoding="utf-8", newline="\n")
        typer.echo(f"Riport: {path}")
    if metrics.safety_failures:
        raise typer.Exit(1)


async def _retrieval_outcomes(top_k: int) -> "tuple[list[RetrievalOutcome], str | None]":
    from finql.core.db import create_engine, create_sessionmaker
    from finql.eval.retrieval import load_retrieval, run_retrieval_eval
    from finql.llm.embeddings import VoyageEmbedder, build_embedder
    from finql.rag.retriever import Retriever

    settings = get_settings()
    embedder = build_embedder(settings)
    engine = create_engine(settings.database_url.get_secret_value())
    try:
        retriever = Retriever(create_sessionmaker(engine), embedder)
        outcomes = await run_retrieval_eval(retriever, load_retrieval(), top_k=top_k)
    finally:
        if isinstance(embedder, VoyageEmbedder):
            await embedder.close()
        await engine.dispose()
    return outcomes, embedder.model if embedder is not None else None


@audit_app.command("verify")
def audit_verify(
    anchor: Annotated[
        Path | None,
        typer.Option(
            help="Horgonyfájl (JSON) a korábban rögzített láncfejekkel. Ha létezik, a fejeknek "
            "még egyezniük kell; ha minden ép, a fájl a mostani fejekre frissül. Tartsd az "
            "adatbázison kívül.",
        ),
    ] = None,
) -> None:
    """A hash-láncolt naplók (query_log, answer_log) ellenőrzése. Hibánál a kilépési kód 1."""
    import json

    anchors: dict[str, dict[str, object]] = {}
    if anchor is not None and anchor.exists():
        anchors = json.loads(anchor.read_text(encoding="utf-8"))
    statuses, mismatches = asyncio.run(_verify_logs(anchors))

    for status in statuses:
        if status.intact:
            head = f", fej: {status.head_seq} {status.head_hash}" if status.head_seq else ""
            typer.echo(f"  {status.log:<12} ép: {status.checked} sor{head}")
        else:
            typer.echo(
                f"  {status.log:<12} MEGSZAKAD a {status.broken_at}. sornál ({status.problem}), "
                f"előtte {status.checked} sor ép"
            )
    for log, message in mismatches:
        typer.echo(f"  {log:<12} HORGONY: {message}")

    if mismatches or not all(status.intact for status in statuses):
        raise typer.Exit(1)
    if anchor is not None:
        heads = {s.log: {"seq": s.head_seq, "hash": s.head_hash} for s in statuses if s.head_seq}
        anchor.write_text(json.dumps(heads, indent=2) + "\n", encoding="utf-8")
        typer.echo(f"Horgony frissítve: {anchor}")


async def _verify_logs(
    anchors: dict[str, dict[str, object]],
) -> "tuple[list[ChainStatus], list[tuple[str, str]]]":
    from finql.audit.service import anchor_mismatch, verify_chains
    from finql.core.db import create_engine, create_sessionmaker

    engine = create_engine(get_settings().database_url.get_secret_value())
    try:
        async with create_sessionmaker(engine)() as session:
            statuses = await verify_chains(session)
            mismatches = []
            for log, head in anchors.items():
                message = await anchor_mismatch(
                    session, log, int(str(head["seq"])), str(head["hash"])
                )
                if message is not None:
                    mismatches.append((log, message))
    finally:
        await engine.dispose()
    return statuses, mismatches


@app.command()
def mcp() -> None:
    """MCP-szerver stdio-n (Claude Desktop, Claude Code): az agent eszközei a FINQL_MCP_EMAIL
    felhasználó jogaival. Az MCP-kliens indítja, nem kézzel."""
    from finql.core.errors import NotAuthenticatedError
    from finql.mcp.server import serve_stdio

    try:
        asyncio.run(serve_stdio(get_settings()))
    except NotAuthenticatedError as exc:
        # stderr: the client shows it in its log; stdout belongs to the protocol.
        typer.echo(f"Az MCP-szerver nem indult: {exc.message}", err=True)
        raise typer.Exit(1) from exc

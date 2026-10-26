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


examples_app = typer.Typer(help="Few-shot példák kezelése.", no_args_is_help=True)
app.add_typer(examples_app, name="examples")
eval_app = typer.Typer(help="A text-to-SQL minőségének mérése.", no_args_is_help=True)
app.add_typer(eval_app, name="eval")


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

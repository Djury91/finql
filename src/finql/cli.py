import io
import sys
import time
from typing import Annotated

import typer

from finql import __version__
from finql.core.config import get_settings

app = typer.Typer(help="FinQL parancssori eszközök.", no_args_is_help=True)
db_app = typer.Typer(help="Adatbázis-adminisztráció.", no_args_is_help=True)
app.add_typer(db_app, name="db")


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
    url = get_settings().migration_database_url
    if url is None:
        typer.echo("Hiányzik a FINQL_MIGRATION_DATABASE_URL (lásd .env.example).", err=True)
        raise typer.Exit(1)

    started = time.perf_counter()
    try:
        counts = load(
            psycopg_conninfo(url.get_secret_value()),
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

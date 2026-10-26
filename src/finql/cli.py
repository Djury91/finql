import typer

from finql import __version__

app = typer.Typer(help="FinQL parancssori eszközök.", no_args_is_help=True)


@app.callback()
def main() -> None:
    """FinQL parancssori eszközök."""


@app.command()
def version() -> None:
    """A telepített FinQL-verzió kiírása."""
    typer.echo(__version__)

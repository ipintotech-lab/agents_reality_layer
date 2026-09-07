import typer

from reality_layer import __version__

app = typer.Typer(help="Reality Layer command line tools.")


@app.callback()
def main(
    version: bool = typer.Option(False, "--version", help="Show the installed version."),
) -> None:
    if version:
        typer.echo(__version__)
        raise typer.Exit()


@app.command()
def init() -> None:
    typer.echo("Initialized observe-only Reality Layer workspace.")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind host."),
    port: int = typer.Option(8000, help="Bind port."),
) -> None:
    import uvicorn

    uvicorn.run("reality_layer.api.app:app", host=host, port=port, reload=False)

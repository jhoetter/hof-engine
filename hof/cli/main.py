"""hof CLI entry point."""

from __future__ import annotations

import click
import typer

from hof.cli.commands import add as add_cmd
from hof.cli.commands import db, dev, flow, fn, new, table, cron_cmd

_typer_app = typer.Typer(
    name="hof",
    help="hof-engine: Full-stack Python + React framework.",
    no_args_is_help=True,
)

_typer_app.add_typer(dev.app, name="dev", help="Start the development server.")
_typer_app.add_typer(flow.app, name="flow", help="Manage and run flows.")
_typer_app.add_typer(table.app, name="table", help="Interact with tables.")
_typer_app.add_typer(db.app, name="db", help="Database migration commands.")
_typer_app.add_typer(cron_cmd.app, name="cron", help="Manage cron jobs.")
_typer_app.add_typer(new.app, name="new", help="Scaffold new components.")
_typer_app.add_typer(add_cmd.app, name="add", help="Add modules from hof-components.")


@_typer_app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-v", help="Show version."),
) -> None:
    if version:
        from hof import __version__

        typer.echo(f"hof-engine {__version__}")
        raise typer.Exit()


app: click.Group = typer.main.get_group(_typer_app)
app.add_command(fn.app, "fn")


if __name__ == "__main__":
    app()

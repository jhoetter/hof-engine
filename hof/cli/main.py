"""hof CLI entry point."""

from __future__ import annotations

import typer

from hof.cli.commands import db, dev, flow, fn, new, table, cron_cmd

app = typer.Typer(
    name="hof",
    help="hof-engine: Full-stack Python + React framework.",
    no_args_is_help=True,
)

app.add_typer(dev.app, name="dev", help="Start the development server.")
app.add_typer(flow.app, name="flow", help="Manage and run flows.")
app.add_typer(fn.app, name="fn", help="Call and manage functions.")
app.add_typer(table.app, name="table", help="Interact with tables.")
app.add_typer(db.app, name="db", help="Database migration commands.")
app.add_typer(cron_cmd.app, name="cron", help="Manage cron jobs.")
app.add_typer(new.app, name="new", help="Scaffold new components.")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-v", help="Show version."),
) -> None:
    if version:
        from hof import __version__

        typer.echo(f"hof-engine {__version__}")
        raise typer.Exit()


if __name__ == "__main__":
    app()

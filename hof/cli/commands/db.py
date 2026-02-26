"""hof db -- database migration commands."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from hof.cli.commands import bootstrap

app = typer.Typer()
console = Console()


@app.command("migrate")
def migrate(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show SQL without applying."),
) -> None:
    """Generate and apply pending migrations."""
    from hof.db.migrations import run_migrations

    bootstrap()
    from hof.config import get_config

    project_root = Path.cwd()
    config = get_config()

    console.print("[cyan]Running migrations...[/]")
    run_migrations(project_root, config, dry_run=dry_run)
    if dry_run:
        console.print("[dim]Dry run complete -- no changes applied.[/]")
    else:
        console.print("[green]Migrations applied successfully.[/]")


@app.command("rollback")
def rollback(
    steps: int = typer.Option(1, "--steps", "-s", help="Number of migrations to rollback."),
) -> None:
    """Rollback the last migration(s)."""
    from hof.db.migrations import rollback_migrations

    bootstrap()
    from hof.config import get_config

    console.print(f"[yellow]Rolling back {steps} migration(s)...[/]")
    rollback_migrations(Path.cwd(), get_config(), steps=steps)
    console.print("[green]Rollback complete.[/]")


@app.command("history")
def history() -> None:
    """Show migration history."""
    from hof.db.migrations import get_migration_history

    bootstrap()
    from hof.config import get_config

    entries = get_migration_history(Path.cwd(), get_config())
    if not entries:
        console.print("[dim]No migrations found.[/]")
        return

    for entry in entries:
        console.print(f"  {entry}")


@app.command("current")
def current() -> None:
    """Show current migration state."""
    from hof.db.migrations import get_current_revision

    bootstrap()
    from hof.config import get_config

    revision = get_current_revision(Path.cwd(), get_config())
    console.print(f"Current revision: {revision or '[dim]none[/]'}")

"""hof db -- database migration commands."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer()
console = Console()


@app.command("migrate")
def migrate(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show SQL without applying."),
) -> None:
    """Generate and apply pending migrations."""
    from hof.config import load_config
    from hof.core.discovery import discover_all
    from hof.db.migrations import run_migrations

    project_root = Path.cwd()
    config = load_config(project_root)
    discover_all(project_root, config.discovery_dirs)

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
    from hof.config import load_config
    from hof.db.migrations import rollback_migrations

    project_root = Path.cwd()
    config = load_config(project_root)

    console.print(f"[yellow]Rolling back {steps} migration(s)...[/]")
    rollback_migrations(project_root, config, steps=steps)
    console.print("[green]Rollback complete.[/]")


@app.command("history")
def history() -> None:
    """Show migration history."""
    from hof.config import load_config
    from hof.db.migrations import get_migration_history

    project_root = Path.cwd()
    config = load_config(project_root)

    entries = get_migration_history(project_root, config)
    if not entries:
        console.print("[dim]No migrations found.[/]")
        return

    for entry in entries:
        console.print(f"  {entry}")


@app.command("current")
def current() -> None:
    """Show current migration state."""
    from hof.config import load_config
    from hof.db.migrations import get_current_revision

    project_root = Path.cwd()
    config = load_config(project_root)

    revision = get_current_revision(project_root, config)
    console.print(f"Current revision: {revision or '[dim]none[/]'}")

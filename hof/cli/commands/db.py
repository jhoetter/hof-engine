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


@app.command("reset")
def reset(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Drop all tables and re-run migrations from scratch."""
    from sqlalchemy import text

    bootstrap()
    from hof.config import get_config
    from hof.db.engine import get_engine
    from hof.db.migrations import run_migrations

    config = get_config()

    if not yes:
        confirm = typer.confirm(
            f"This will DROP ALL TABLES in {config.database_url.split('@')[-1]}. Continue?"
        )
        if not confirm:
            raise typer.Abort()

    console.print("[yellow]Dropping all tables...[/]")
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.commit()

    console.print("[cyan]Re-running migrations...[/]")

    migrations_dir = Path.cwd() / "migrations"
    versions_dir = migrations_dir / "versions"
    if versions_dir.is_dir():
        for f in versions_dir.glob("*.py"):
            f.unlink()
        console.print("  [dim]Cleared old migration files[/]")

    run_migrations(Path.cwd(), config)
    console.print("[green]Database reset complete.[/]")

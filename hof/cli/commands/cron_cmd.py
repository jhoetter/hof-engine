"""hof cron -- manage cron jobs."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table as RichTable

app = typer.Typer()
console = Console()


def _ensure_discovered() -> None:
    from hof.config import load_config
    from hof.core.discovery import discover_all

    config = load_config(Path.cwd())
    discover_all(Path.cwd(), config.discovery_dirs)


@app.command("list")
def list_cron() -> None:
    """List all registered cron jobs."""
    _ensure_discovered()
    from hof.core.registry import registry

    table = RichTable(title="Registered Cron Jobs")
    table.add_column("Name", style="cyan")
    table.add_column("Schedule")
    table.add_column("Timezone")
    table.add_column("Enabled")

    for name, meta in registry.cron_jobs.items():
        table.add_row(
            name,
            meta.schedule,
            meta.timezone,
            "yes" if meta.enabled else "no",
        )

    console.print(table)


@app.command("run")
def run_cron(
    cron_name: str = typer.Argument(help="Cron job name to trigger manually."),
) -> None:
    """Manually trigger a cron job."""
    _ensure_discovered()
    from hof.core.registry import registry

    meta = registry.get_cron(cron_name)
    if meta is None:
        console.print(f"[red]Cron job '{cron_name}' not found.[/]")
        raise typer.Exit(1)

    console.print(f"[cyan]Running {cron_name}...[/]")
    meta.fn()
    console.print(f"[green]Completed.[/]")


@app.command("enable")
def enable_cron(
    cron_name: str = typer.Argument(help="Cron job name."),
) -> None:
    """Enable a cron job."""
    _ensure_discovered()
    from hof.core.registry import registry

    meta = registry.get_cron(cron_name)
    if meta is None:
        console.print(f"[red]Cron job '{cron_name}' not found.[/]")
        raise typer.Exit(1)

    meta.enabled = True
    console.print(f"[green]Enabled {cron_name}.[/]")


@app.command("disable")
def disable_cron(
    cron_name: str = typer.Argument(help="Cron job name."),
) -> None:
    """Disable a cron job."""
    _ensure_discovered()
    from hof.core.registry import registry

    meta = registry.get_cron(cron_name)
    if meta is None:
        console.print(f"[red]Cron job '{cron_name}' not found.[/]")
        raise typer.Exit(1)

    meta.enabled = False
    console.print(f"[yellow]Disabled {cron_name}.[/]")

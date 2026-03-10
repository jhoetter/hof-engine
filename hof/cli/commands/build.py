"""hof build -- production build for the UI."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer()
console = Console()


@app.callback(invoke_without_command=True)
def build(ctx: typer.Context) -> None:
    """Build the UI for production (generates setup files and runs vite build)."""
    from hof.config import load_config
    from hof.ui.vite import ViteManager

    project_root = Path.cwd()
    config = load_config(project_root)
    ui_dir = project_root / config.ui_dir

    if not ui_dir.is_dir():
        console.print("[dim]No ui/ directory found, nothing to build.[/]")
        raise typer.Exit()

    manager = ViteManager(ui_dir, app_name=config.app_name, project_root=project_root)
    console.print(f"[cyan]Building UI[/] in {config.ui_dir}/")
    manager.build()
    console.print("[green]Build complete.[/]")

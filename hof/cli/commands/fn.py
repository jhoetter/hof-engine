"""hof fn -- call and manage functions."""

from __future__ import annotations

import asyncio
import json
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


@app.callback(invoke_without_command=True)
def call_function(
    ctx: typer.Context,
    function_name: str = typer.Argument(None, help="Function name to call."),
    input_json: str = typer.Option(None, "--json", "-j", help="JSON input."),
) -> None:
    """Call a function by name. Pass arguments as --key=value or --json '{...}'."""
    if ctx.invoked_subcommand is not None:
        return
    if function_name is None:
        console.print("[dim]Use 'hof fn list' to see available functions.[/]")
        raise typer.Exit()

    _ensure_discovered()
    from hof.core.registry import registry

    meta = registry.get_function(function_name)
    if meta is None:
        console.print(f"[red]Function '{function_name}' not found.[/]")
        raise typer.Exit(1)

    if input_json:
        kwargs = json.loads(input_json)
    else:
        kwargs = _parse_cli_kwargs(ctx.args)

    if meta.is_async:
        result = asyncio.run(meta.fn(**kwargs))
    else:
        result = meta.fn(**kwargs)

    console.print_json(json.dumps(result, default=str))


@app.command("list")
def list_functions() -> None:
    """List all registered functions."""
    _ensure_discovered()
    from hof.core.registry import registry

    table = RichTable(title="Registered Functions")
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Tags")
    table.add_column("Async")

    for name, meta in registry.functions.items():
        table.add_row(
            name,
            meta.description[:60] + "..." if len(meta.description) > 60 else meta.description,
            ", ".join(meta.tags) if meta.tags else "-",
            "yes" if meta.is_async else "no",
        )

    console.print(table)


@app.command("schema")
def show_schema(
    function_name: str = typer.Argument(help="Function name."),
) -> None:
    """Show the input/output schema of a function."""
    _ensure_discovered()
    from hof.core.registry import registry

    meta = registry.get_function(function_name)
    if meta is None:
        console.print(f"[red]Function '{function_name}' not found.[/]")
        raise typer.Exit(1)

    console.print_json(json.dumps(meta.to_dict(), default=str))


def _parse_cli_kwargs(args: list[str]) -> dict:
    """Parse --key=value pairs from CLI arguments."""
    kwargs: dict = {}
    for arg in args:
        if arg.startswith("--"):
            key_val = arg[2:]
            if "=" in key_val:
                key, val = key_val.split("=", 1)
            else:
                key = key_val
                val = "true"
            kwargs[key.replace("-", "_")] = val
    return kwargs
